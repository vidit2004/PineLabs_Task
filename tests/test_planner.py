import io
import json

import pytest

from analyst import planner
from analyst.plan import Clarification


def stub_provider(monkeypatch, question, output, expected_window=None):
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def respond(request, timeout):
        body = json.loads(request.data)
        assert body["contents"] == [{"role": "user", "parts": [{"text": question}]}]
        instructions = body["systemInstruction"]["parts"]
        assert instructions[0] == {"text": planner.CATALOG}
        if expected_window:
            assert len(instructions) == 2
            context = instructions[1]["text"]
            assert "exclusive" in context
            assert json.loads(context[context.index("{"):]) == expected_window
        else:
            assert len(instructions) == 1
        assert request.full_url.endswith("/models/test-model:generateContent")
        assert request.get_header("X-goog-api-key") == "test-key"
        assert timeout == 30
        if isinstance(output, Exception):
            raise output
        candidate = {"finishReason": "STOP", "content": {"parts": [{"text": output}]}}
        return io.BytesIO(json.dumps({"candidates": [candidate]}).encode())

    monkeypatch.setattr(planner, "urlopen", respond)


@pytest.mark.parametrize("question", [planner.QUESTION, planner.PARAPHRASE])
def test_modes_agree(monkeypatch, question):
    stub_provider(monkeypatch, question, planner.PRESET.model_dump_json())
    assert planner.plan_question(question, "live") == planner.plan_question(question, "offline") == planner.PRESET


@pytest.mark.parametrize("question,output", [
    ("Compare success rates by bank", '{"question":"Which two date ranges should I compare?"}'),
    ("Compare revenue", planner.PRESET.model_dump_json().replace("success_rate", "revenue")),
    (planner.QUESTION, "invalid JSON"),
    (planner.QUESTION, TimeoutError()),
])
def test_non_answers_skip_execution(monkeypatch, tmp_path, question, output):
    stub_provider(monkeypatch, question, output)
    monkeypatch.setattr(planner, "analyze_fixture", lambda *args: pytest.fail("Unexpected execution"))
    if question == "Compare success rates by bank":
        result = planner.ask(question, "live", tmp_path)
        assert isinstance(result, Clarification) and "date ranges" in result.question
    else:
        with pytest.raises(planner.PlannerError):
            planner.ask(question, "live", tmp_path)
    assert planner.plan_question(planner.QUESTION, "offline") == planner.PRESET


def test_live_comparison_uses_validated_filter(monkeypatch):
    from pathlib import Path

    question = "Compare sample weeks for Bank B"
    payload = planner.PRESET.model_dump(mode="json") | {"bank_ids": ["B"]}
    stub_provider(monkeypatch, question, json.dumps(payload))
    answer = planner.ask(question, "live", Path(__file__).resolve().parents[1] / "data/fixtures/clean")
    assert [(row.bank_id, row.attempts) for row in answer.rows] == [("B", 200), ("B", 600)]


def test_daily_planner_modes_and_missing_dates(monkeypatch, tmp_path):
    stub_provider(monkeypatch, planner.TREND_QUESTION, planner.TREND_PRESET.model_dump_json(),
                  {"start": "2026-10-05", "end": "2026-10-19"})
    for mode in ("live", "offline"):
        assert planner.plan_question(planner.TREND_QUESTION, mode) == planner.TREND_PRESET
    question = "Show daily payment success"
    stub_provider(monkeypatch, question, '{"question":"Which start and final IST dates should I use?"}')
    for mode in ("live", "offline"):
        answer = planner.ask(question, mode, tmp_path)
        assert isinstance(answer, Clarification) and "dates" in answer.question


@pytest.mark.parametrize("wording,start,end", [
    ("October 5 through October 18, 2026", "2026-10-05", "2026-10-19"),
    ("2026-10-05 through 2026-10-18", "2026-10-05", "2026-10-19"),
    ("October 1 through October 31, 2026", "2026-10-01", "2026-11-01"),
    ("December 28 through January 3, 2027", "2026-12-28", "2027-01-04"),
])
def test_python_window_passed_to_live_planner(monkeypatch, wording, start, end):
    question = "Show daily payment success from " + wording
    expected = {"start": start, "end": end}
    payload = planner.TREND_PRESET.model_dump(mode="json") | {"window": expected}
    stub_provider(monkeypatch, question, json.dumps(payload), expected)
    assert planner.plan_question(question, "live").window.model_dump(mode="json") == expected


@pytest.mark.parametrize("dates", ["", " in October", " from 05/10/26 to 18/10/26",
                                   " from October 5 through October 18",
                                   " from October 5 through October 18, 2026 or October 20"])
def test_unclear_dates_stop_before_provider_or_sql(monkeypatch, tmp_path, dates):
    monkeypatch.setattr(planner, "gemini", lambda *args: pytest.fail("Unexpected model call"))
    result = planner.ask("Show daily payment success" + dates, "live", tmp_path)
    assert isinstance(result, Clarification)


def test_32_days_stop_before_provider_or_sql(monkeypatch, tmp_path):
    monkeypatch.setattr(planner, "gemini", lambda *args: pytest.fail("Unexpected model call"))
    with pytest.raises(planner.PlannerError, match="1 to 31"):
        planner.ask("Show daily payment success from 2026-10-01 to 2026-11-01", "live", tmp_path)


def test_model_cannot_shift_trend_window(monkeypatch, tmp_path):
    payload = planner.TREND_PRESET.model_dump(mode="json")
    payload["window"]["end"] = "2026-10-20"
    stub_provider(monkeypatch, planner.TREND_QUESTION, json.dumps(payload),
                  {"start": "2026-10-05", "end": "2026-10-19"})
    with pytest.raises(planner.PlannerError, match="does not match"):
        planner.ask(planner.TREND_QUESTION, "live", tmp_path)
