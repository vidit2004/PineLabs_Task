import io
import json

import pytest

from analyst import planner
from analyst.plan import Clarification


def stub_provider(monkeypatch, question, output):
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def respond(request, timeout):
        body = json.loads(request.data)
        assert body["contents"] == [{"role": "user", "parts": [{"text": question}]}]
        assert body["systemInstruction"]["parts"] == [{"text": planner.CATALOG}]
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
