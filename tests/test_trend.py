import sqlite3
from datetime import date
from fractions import Fraction
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from analyst.data import QualityError, analyze_fixture, execute_plan, stage
from analyst.planner import TREND_PRESET

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"


def test_daily_fixture_counts_and_window():
    trend = analyze_fixture(FIXTURES / "clean", TREND_PRESET)
    assert [row.day for row in trend.rows] == [date(2026, 10, day) for day in range(5, 19)]
    assert [row.successes for row in trend.rows] == [138]*5 + [137]*2 + [132]*3 + [131]*4
    assert [row.attempts for row in trend.rows] == [144,144,143,143,142,142,142,144,143,143,143,143,142,142]
    assert trend.rows[0].rate == Fraction(138, 144)
    assert trend.parameters == {"window_start": "2026-10-05", "window_end": "2026-10-19"}
    with pytest.raises(QualityError, match="missing status"):
        analyze_fixture(FIXTURES / "broken", TREND_PRESET)


def test_empty_days_and_zero_success_are_distinct(tmp_path):
    database = tmp_path / "trend.sqlite"
    stage(FIXTURES / "clean", database)
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM transactions WHERE event_date_ist IN ('2026-10-05','2026-10-10','2026-10-18')")
        db.execute("UPDATE transactions SET status='FAILED' WHERE event_date_ist='2026-10-11'")
    db.close()
    rows = execute_plan(database, TREND_PRESET).rows
    assert len(rows) == 14
    for row in (rows[0], rows[5], rows[-1]):
        assert (row.successes, row.attempts, row.rate) == (0, 0, None)
    assert rows[6].attempts == 142 and rows[6].rate == 0


def test_daily_screen_and_evidence():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.button[2].click().run()
    app.button[0].click().run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 14
    assert "GROUP BY event_date_ist" in app.code[0].value
    app.radio[1].set_value("Broken")
    app.button[0].click().run()
    assert "missing status" in app.error[0].value
    assert not app.dataframe and not app.expander
