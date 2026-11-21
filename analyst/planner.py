"""Plan a comparison from a question and execute only validated plans."""
import json
import os
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import TypeAdapter, ValidationError

from .data import analyze_fixture
from .plan import AnalysisPlan, Clarification, TrendPlan

QUESTION = ("Why did payment success rate fall from October 5–11 to October 12–18, "
            "2026? Break it down by bank.")
PARAPHRASE = "Compare payment success by bank for Oct 5-11 and Oct 12-18, 2026."
PRESET = AnalysisPlan(intent="compare", metric="success_rate", group_by="bank",
                      baseline={"start": "2026-10-05", "end": "2026-10-12"},
                      current={"start": "2026-10-12", "end": "2026-10-19"})
TREND_QUESTION = "Show daily payment success from October 5 through October 18, 2026"
TREND_PRESET = TrendPlan(intent="trend", metric="success_rate", group_by="overall",
                        window={"start": "2026-10-05", "end": "2026-10-19"})
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


def gemini(question: str) -> str:
    key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL")
    if not key or not model:
        raise PlannerError("Live planning requires GEMINI_API_KEY and GEMINI_MODEL.")
    body = {"systemInstruction": {"parts": [{"text": CATALOG}]},
            "contents": [{"role": "user", "parts": [{"text": question}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    request = Request("https://generativelanguage.googleapis.com/v1beta/models/"
                      + quote(model, safe="") + ":generateContent",
                      data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json", "x-goog-api-key": key})
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
        if normalize(question).rstrip(".?") == normalize(TREND_QUESTION):
            return TREND_PRESET
        if "daily" in question.casefold():
            return Clarification(question="Which start and final IST dates should I use? Select the daily "
                                 "sample question for the offline example, or use Gemini for a custom range.")
        return Clarification(question="Use the shipped sample question or choose live mode for other wording.")
    if mode != "live":
        raise PlannerError("Choose live or offline mode.")
    raw = gemini(question)
    try:
        outcome = OUTPUT.validate_json(raw)
    except ValidationError as exc:
        raise PlannerError("Gemini returned an invalid or unsupported plan.") from exc
    if not isinstance(outcome, Clarification) and set(outcome.bank_ids or ()) - {"A", "B"}:
        raise PlannerError("Choose Bank A or Bank B.")
    return outcome


def ask(question: str, mode: str, fixture: Path):
    outcome = plan_question(question, mode)
    if isinstance(outcome, Clarification):
        return outcome
    return analyze_fixture(fixture, outcome)
