import sqlite3
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from analyst.data import QualityError, analyze_fixture, compare, stage
from analyst.plan import AnalysisPlan

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures"
FIELDS = dict(intent="compare", metric="success_rate", group_by="bank",
              baseline=dict(start="2026-10-05", end="2026-10-12"),
              current=dict(start="2026-10-12", end="2026-10-19"))
PLAN = AnalysisPlan(**FIELDS)


def test_clean_broken_clean():
    for variant in ("clean", "broken", "clean"):
        if variant == "broken":
            with pytest.raises(QualityError, match="missing status in current.*1 affected"):
                analyze_fixture(FIXTURES / variant, PLAN)
            continue
        result = analyze_fixture(FIXTURES / variant, PLAN)
        assert [(r.period, r.bank_id, r.successes, r.attempts) for r in result.rows] == [
            ("baseline", "A", 784, 800), ("baseline", "B", 180, 200),
            ("current", "A", 392, 400), ("current", "B", 528, 600)]
        assert result.rates == {"baseline": Fraction("0.964"), "current": Fraction("0.920")}
        assert result.mix_pp == Fraction("-3.2")
        assert result.performance_pp == Fraction("-1.2")
        assert result.mix_pp + result.performance_pp == 100 * (result.rates["current"] - result.rates["baseline"])


@pytest.mark.parametrize("statement,error", [
    ("INSERT INTO banks VALUES ('A','Other')", "duplicate"),
    ("INSERT INTO transactions SELECT * FROM transactions LIMIT 1", "duplicate attempt"),
    ("UPDATE transactions SET bank_id='X'", "unmatched bank"),
    ("UPDATE transactions SET status='PENDING'", "invalid status"),
])
def test_quality(tmp_path, statement, error):
    path = tmp_path / "data.sqlite"
    stage(FIXTURES / "clean", path)
    with sqlite3.connect(path) as db:
        db.execute(statement)
    db.close()
    with pytest.raises(QualityError, match=error):
        compare(path, PLAN)


def test_binding_and_boundaries(tmp_path):
    path = tmp_path / "data.sqlite"
    stage(FIXTURES / "broken", path)
    with sqlite3.connect(path) as db:
        db.executemany("INSERT INTO transactions VALUES (?, ?, 'B', 'SUCCESS')",
                       [("inside", "2026-10-12"), ("outside", "2026-10-19")])
    db.close()
    result = compare(path, AnalysisPlan(**FIELDS, bank_ids=["B"]))
    assert [r.attempts for r in result.rows] == [200, 601]
    assert ":bank_0" in result.sql and result.parameters["bank_0"] == "B"


@pytest.mark.parametrize("changes", [dict(group_by="merchant"), dict(raw_sql="SELECT 1"),
                                     dict(current=dict(start="2026-10-11", end="2026-10-18")),
                                     dict(bank_ids=[123])])
def test_plan_validation(changes):
    with pytest.raises(ValidationError):
        AnalysisPlan(**(FIELDS | changes))


@pytest.mark.parametrize("bank", ["A", None])
def test_missing_observations_preserve_supported_rates(tmp_path, bank):
    path = tmp_path / "data.sqlite"
    stage(FIXTURES / "clean", path)
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM transactions WHERE event_date_ist >= '2026-10-12' "
                   "AND (? IS NULL OR bank_id = ?)", (bank, bank))
    db.close()
    answer = compare(path, PLAN)
    assert answer.rates["baseline"] == Fraction("0.964")
    assert answer.rates["current"] == (Fraction("0.88") if bank else None)
    assert answer.mix_pp is answer.performance_pp is None
    assert answer.limitation
