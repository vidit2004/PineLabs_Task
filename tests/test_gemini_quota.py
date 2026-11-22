import io
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from analyst import planner


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "mock-model")
    monkeypatch.setenv("GEMINI_API_KEY", "mock-provider-key")
    monkeypatch.setenv("GEMINI_DAILY_LIMIT", "100")
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://quota.invalid")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "mock-token")


def test_shared_attempt_limit_and_ist_rollover(configured, monkeypatch):
    clock = Mock()
    moment = datetime(2026, 10, 18, 18, 29, 59, tzinfo=timezone.utc)
    clock.now.side_effect = lambda tz: moment.astimezone(tz)
    monkeypatch.setattr(planner, "datetime", clock)
    reserved = Counter()
    attempts = []

    def respond(request, timeout):
        if request.full_url == "https://quota.invalid":
            command, script, key_count, key, limit = json.loads(request.data)
            assert (command, script, key_count, limit) == ("EVAL", planner.RESERVE_REQUEST, "1", "100")
            assert request.get_header("Authorization") == "Bearer mock-token"
            allowed = reserved[key] < int(limit)
            reserved[key] += int(allowed)
            return io.BytesIO(json.dumps({"result": int(allowed)}).encode())
        assert request.full_url.endswith(":generateContent")
        attempts.append(request)
        if len(attempts) == 1:
            raise TimeoutError()
        return io.BytesIO(b'{"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":"ok"}]}}]}')

    monkeypatch.setattr(planner, "urlopen", respond)
    with pytest.raises(planner.PlannerError, match="timed out"):
        planner.gemini("first attempt")
    for _ in range(99):
        assert planner.gemini("next attempt") == "ok"
    with pytest.raises(planner.PlannerError, match="quota reached"):
        planner.gemini("attempt 101")
    assert len(attempts) == 100
    moment = datetime(2026, 10, 18, 18, 30, tzinfo=timezone.utc)
    assert planner.gemini("after midnight IST") == "ok"
    assert reserved == {"bizilytix:gemini:daily:2026-10-18": 100, "bizilytix:gemini:daily:2026-10-19": 1}


@pytest.mark.parametrize("reply", [TimeoutError(), b'{"error":"unavailable"}', b'{"result":true}', b'not json'])
def test_redis_failure_blocks_live_but_offline_works(configured, monkeypatch, reply):
    def respond(request, timeout):
        assert request.full_url == "https://quota.invalid"
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(reply)

    monkeypatch.setattr(planner, "urlopen", respond)
    fixture = Path(__file__).resolve().parents[1] / "data/fixtures/clean"
    with pytest.raises(planner.PlannerError, match="quota service"):
        planner.ask(planner.QUESTION, "live", fixture)
    assert len(planner.ask(planner.QUESTION, "offline", fixture).rows) == 4


@pytest.mark.parametrize("setting,value", [
    ("GEMINI_DAILY_LIMIT", ""), ("GEMINI_DAILY_LIMIT", "-1"), ("GEMINI_DAILY_LIMIT", "1.5"),
    ("UPSTASH_REDIS_REST_URL", "http://quota.invalid"), ("UPSTASH_REDIS_REST_TOKEN", ""),
])
def test_invalid_quota_blocks_before_network(configured, monkeypatch, setting, value):
    monkeypatch.setenv(setting, value)
    monkeypatch.setattr(planner, "urlopen", lambda *a, **kw: pytest.fail("Unexpected network call"))
    with pytest.raises(planner.PlannerError, match="configuration"):
        planner.gemini("test")
