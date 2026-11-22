import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from analyst import planner
from analyst.data import AccessDenied, DemoRole, analyze_fixture, execute_plan, stage

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data/fixtures/clean"
VIEWER = DemoRole.BANK_A_VIEWER


@pytest.mark.parametrize("preset", [planner.PRESET, planner.TREND_PRESET])
@pytest.mark.parametrize("banks", [("B",), ("A", "B")])
def test_explicit_denial_precedes_database_access(preset, banks, tmp_path):
    plan = preset.model_copy(update={"bank_ids": banks})
    with pytest.raises(AccessDenied):
        analyze_fixture(tmp_path / "missing-fixture", plan, VIEWER)
    with pytest.raises(AccessDenied):
        execute_plan(tmp_path / "missing.sqlite", plan, VIEWER)


def test_viewer_scope_applies_to_quality_counts_and_sql(tmp_path):
    database = tmp_path / "data.sqlite"
    stage(CLEAN, database)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE transactions SET status='' WHERE bank_id='B'")
        db.execute("INSERT INTO banks VALUES ('B','Duplicate')")
        comparison = execute_plan(database, planner.PRESET, VIEWER)
        assert db.execute(comparison.sql, comparison.parameters).fetchall() == [
            ("baseline", "A", "Bank A", 800, 784), ("current", "A", "Bank A", 400, 392)]
        trend = execute_plan(database, planner.TREND_PRESET, VIEWER)
        counts = db.execute(trend.sql, trend.parameters).fetchall()
        assert sum(attempts for _, attempts, _ in counts) == 1200
        assert sum(successes for _, _, successes in counts) == 1176
    db.close()


def test_model_filter_checked_even_without_bank_name(monkeypatch):
    monkeypatch.setattr(planner, "plan_question", lambda *_: planner.PRESET.model_copy(update={"bank_ids": ("B",)}))
    with pytest.raises(AccessDenied):
        planner.ask("Show the sample comparison", "live", CLEAN, VIEWER)


def test_role_change_and_denial_clear_previous_chart_and_sql():
    screen = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    screen.button[0].click().run()
    assert "Bank B" in screen.dataframe[0].value["Bank"].tolist()
    screen.selectbox[0].set_value(VIEWER.value).run()
    assert not screen.metric and not screen.get("arrow_vega_lite_chart") and not screen.expander
    screen.button[0].click().run()
    assert set(screen.dataframe[0].value["Bank"]) == {"Bank A"}
    chart = screen.get("arrow_vega_lite_chart")[0].proto
    assert b"Bank A" in chart.datasets[0].data.data
    assert b"Bank B" not in chart.datasets[0].data.data
    assert ":bank_0" in screen.code[0].value
    assert any("Effective scope: Bank A" == c.value for c in screen.caption)
    screen.button[3].click().run()
    screen.button[0].click().run()
    assert "Access denied" in screen.error[0].value
    assert not screen.get("arrow_vega_lite_chart") and not screen.dataframe and not screen.code
    screen.selectbox[0].set_value(DemoRole.ANALYST.value).run()
    screen.button[0].click().run()
    assert set(screen.dataframe[0].value["Bank"]) == {"Bank B"}
