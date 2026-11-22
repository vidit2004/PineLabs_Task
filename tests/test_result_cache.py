from datetime import date, timedelta
from pathlib import Path
from shutil import copytree
from unittest.mock import patch

import pytest

from analyst import data, planner
from analyst.plan import Clarification, Window

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures"


def test_live_paraphrase_roles_denial_and_fixture_changes(tmp_path):
    folder = copytree(FIXTURES / "clean", tmp_path / "fixture")
    cache = data.ResultCache()
    analyst = data.DemoRole.ANALYST
    viewer = data.DemoRole.BANK_A_VIEWER
    bank_b = planner.PRESET.model_copy(update={"bank_ids": ("B",)})

    def ask(question, role=analyst):
        return planner.ask(question, "live", folder, role, cache=cache)

    with (patch.object(planner, "gemini", return_value=planner.PRESET.model_dump_json()) as model,
          patch.object(data, "stage", wraps=data.stage) as stage,
          patch.object(data, "_execute", wraps=data._execute) as execute):
        full = ask(planner.QUESTION)
        assert ask(planner.PARAPHRASE) is full
        assert model.call_count == 2
        assert stage.call_count == execute.call_count == 1

        restricted = ask(planner.QUESTION, viewer)
        assert {row.bank_id for row in restricted.rows} == {"A"}
        assert stage.call_count == execute.call_count == 2
        # Identical effective plan, different role.
        model.return_value = planner.PRESET.model_copy(update={"bank_ids": ("A",)}).model_dump_json()
        assert ask(planner.QUESTION) is not restricted
        assert ask(planner.PARAPHRASE, viewer) is restricted
        model.return_value = bank_b.model_dump_json()
        ask(planner.BANK_B_QUESTION)
        with pytest.raises(data.AccessDenied):
            ask(planner.BANK_B_QUESTION, viewer)
        with pytest.raises(data.AccessDenied):
            ask(planner.PARAPHRASE, viewer)
        assert stage.call_count == execute.call_count == 4

        model.return_value = planner.PRESET.model_dump_json()
        banks = folder / "banks.csv"
        banks.write_bytes(banks.read_bytes().replace(b"Bank A", b"Bank X"))
        changed = ask(planner.QUESTION)
        assert changed.rows[0].bank_name == "Bank X"
        transactions = folder / "transactions.csv"
        transactions.write_bytes(transactions.read_bytes().replace(b"SUCCESS", b"FAILED", 1))
        assert ask(planner.QUESTION).rows[0].successes == full.rows[0].successes - 1
        assert stage.call_count == execute.call_count == 6


def test_errors_and_clarifications_are_not_cached():
    cache = data.ResultCache()
    with patch.object(data, "stage", wraps=data.stage) as stage:
        for _ in range(2):
            with pytest.raises(data.QualityError):
                planner.ask(planner.QUESTION, "offline", FIXTURES / "broken", cache=cache)
            assert isinstance(planner.ask("Which dates?", "offline", FIXTURES / "clean", cache=cache), Clarification)
        assert stage.call_count == 2
        assert not cache


def test_session_capacity_and_isolation():
    cache = data.ResultCache()
    start = date(2026, 10, 1)

    def analyze(offset, session):
        day = start + timedelta(days=offset)
        plan = planner.TREND_PRESET.model_copy(update={"window": Window(start=day, end=day + timedelta(days=1))})
        return data.analyze_fixture(FIXTURES / "clean", plan, cache=session)

    first = analyze(0, cache)
    assert analyze(0, data.ResultCache()) is not first
    second = analyze(1, cache)
    for offset in range(2, 32):
        analyze(offset, cache)
    assert analyze(0, cache) is first
    analyze(32, cache)
    assert len(cache) == 32
    assert analyze(0, cache) is first
    assert analyze(1, cache) is not second
