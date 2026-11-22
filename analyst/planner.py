"""Plan a comparison from a question and execute only validated plans."""
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import TypeAdapter, ValidationError

from .data import AccessDenied, DemoRole, ResultCache, analyze_fixture
from .plan import AnalysisPlan, Clarification, TrendPlan, Window
from .trend_dates import resolve_window

QUESTION = ("Why did payment success rate fall from October 5–11 to October 12–18, "
            "2026? Break it down by bank.")
PARAPHRASE = "Compare payment success by bank for Oct 5-11 and Oct 12-18, 2026."
PRESET = AnalysisPlan(intent="compare", metric="success_rate", group_by="bank",
                      baseline=Window(start=date(2026, 10, 5), end=date(2026, 10, 12)),
                      current=Window(start=date(2026, 10, 12), end=date(2026, 10, 19)))
TREND_QUESTION = "Show daily payment success from October 5 through October 18, 2026"
BANK_B_QUESTION = "Compare Bank B payment success for Oct 5-11 and Oct 12-18, 2026."
TREND_PRESET = TrendPlan(intent="trend", metric="success_rate", group_by="overall",
                        window=Window(start=PRESET.baseline.start, end=PRESET.current.end))
CATALOG = """Return a single JSON object. For a bank comparison use:
intent="compare", metric="success_rate", group_by="bank", baseline and current
(each an object with start and end YYYY-MM-DD dates), optional bank_ids (A or B).
Dates in questions are inclusive IST dates; convert to exclusive end dates.
Comparison needs two ordered, non-overlapping windows of equal length (1-31 days).
For daily payment success use intent="trend", metric="success_rate", group_by="overall",
and window={"start":"YYYY-MM-DD","end":"YYYY-MM-DD"} (exclusive end, 1-31 days).
Optional bank_ids may filter either intent. For a trend with missing or relative dates
ask for the start and final IST dates. Never infer the sample dates from a missing range.
Named sample weeks are October 5-11 and October 12-18, 2026.
If either comparison range is missing or relative, ask for both explicit ranges.
For clarification or an unsupported request return only {"question":"..."}
asking for the missing information or a supported comparison. Never invent dates,
substitute metrics, or produce SQL or findings."""
OUTPUT = TypeAdapter(AnalysisPlan | TrendPlan | Clarification)


class PlannerError(ValueError):
    pass


IST = timezone(timedelta(hours=5, minutes=30))
RESERVE_REQUEST = """
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
if used >= tonumber(ARGV[1]) then return 0 end
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], 172800) end
return 1
"""


def reserve_gemini_request():
    limit = os.getenv("GEMINI_DAILY_LIMIT")
    if limit is None:
        return
    if not re.fullmatch(r"[0-9]{1,15}", limit):
        raise PlannerError("Invalid Gemini quota configuration. Set GEMINI_DAILY_LIMIT to a nonnegative integer (up to 15 digits).")
    endpoint = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?", endpoint) or not re.fullmatch(r"[!-~]+", token):
        raise PlannerError("Invalid Gemini quota configuration. Check the Upstash REST URL and token.")

    day = datetime.now(IST).date().isoformat()
    command = ["EVAL", RESERVE_REQUEST, "1", f"bizilytix:gemini:daily:{day}", limit]
    request = Request(endpoint, data=json.dumps(command).encode(),
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            reply = json.load(response)
    except (OSError, HTTPException, ValueError) as exc:
        raise PlannerError("Live Gemini is blocked because the quota service is unavailable.") from exc
    result = reply.get("result") if isinstance(reply, dict) and "error" not in reply else None
    if type(result) is not int or result not in (0, 1):
        raise PlannerError("Live Gemini is blocked because the quota service did not confirm a reservation.")
    if result == 0:
        raise PlannerError("Daily Gemini quota reached. Live requests resume at midnight IST.")


def gemini(question: str, window: Window | None = None) -> str:
    key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL")
    if not key or not model:
        raise PlannerError("Live planning requires GEMINI_API_KEY and GEMINI_MODEL.")
    instructions = [{"text": CATALOG}]
    if window:
        instructions.append({"text": "For a supported daily trend, copy this resolved IST window exactly. "
                             "Its end is already exclusive. " + window.model_dump_json()})
    body = {"systemInstruction": {"parts": instructions},
            "contents": [{"role": "user", "parts": [{"text": question}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    request = Request("https://generativelanguage.googleapis.com/v1beta/models/"
                      + quote(model, safe="") + ":generateContent",
                      data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json", "x-goog-api-key": key})
    reserve_gemini_request()
    try:
        with urlopen(request, timeout=30) as response:
            candidate = json.load(response)["candidates"][0]
        if candidate.get("finishReason") != "STOP":
            raise PlannerError("Gemini did not finish a plan.")
        return "".join(part["text"] for part in candidate["content"]["parts"]
                       if not part.get("thought"))
    except HTTPError as exc:
        raise PlannerError(f"Gemini returned HTTP {exc.code}.") from exc
    except (OSError, HTTPException) as exc:
        raise PlannerError("Gemini timed out or could not be reached.") from exc
    except (KeyError, IndexError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlannerError("Gemini returned an unreadable response.") from exc


def plan_question(question: str, mode: str) -> AnalysisPlan | TrendPlan | Clarification:
    if mode == "offline":
        normalize = lambda value: " ".join(value.casefold().replace("–", "-").split())
        if normalize(question) in {normalize(QUESTION), normalize(PARAPHRASE)}:
            return PRESET
        if normalize(question) == normalize(BANK_B_QUESTION):
            return PRESET.model_copy(update={"bank_ids": ("B",)})
        if normalize(question).rstrip(".?") == normalize(TREND_QUESTION):
            return TREND_PRESET
        if "daily" in question.casefold():
            return Clarification(question="Which start and final IST dates should I use? Select the daily "
                                 "sample question for the offline example, or use Gemini for a custom range.")
        return Clarification(question="Use the shipped sample question or choose live mode for other wording.")
    if mode != "live":
        raise PlannerError("Choose live or offline mode.")
    window = None
    date_question = Clarification(question="Which start and final IST dates should I use for the daily trend?")
    if re.search(r"\b(daily|trend|day.by.day|per day|each day|by day)\b", question, re.I):
        try:
            window = resolve_window(question)
        except (ValueError, OverflowError) as exc:
            raise PlannerError("Choose valid IST dates in order, spanning 1 to 31 days inclusive.") from exc
        if window is None:
            return date_question
    raw = gemini(question, window)
    try:
        outcome = OUTPUT.validate_json(raw)
    except ValidationError as exc:
        raise PlannerError("Gemini returned an invalid or unsupported plan.") from exc
    if isinstance(outcome, TrendPlan) and window is None:
        return date_question
    if window and not isinstance(outcome, Clarification):
        if not isinstance(outcome, TrendPlan) or outcome.window != window:
            raise PlannerError("Gemini returned a plan that does not match the requested daily window.")
    if not isinstance(outcome, Clarification) and set(outcome.bank_ids or ()) - {"A", "B"}:
        raise PlannerError("Choose Bank A or Bank B.")
    return outcome


def ask(question: str, mode: str, fixture: Path, role=DemoRole.ANALYST, *, cache: ResultCache | None = None):
    role = DemoRole(role)
    if role == DemoRole.BANK_A_VIEWER and re.search(r"\bbanks?\s+(?:b\b|a\s*(?:and|&|,|/)\s*b\b)|\bboth banks\b",
                                                    question, re.I):
        raise AccessDenied()
    outcome = plan_question(question, mode)
    if isinstance(outcome, Clarification):
        return outcome
    return analyze_fixture(fixture, outcome, role, cache=cache)
