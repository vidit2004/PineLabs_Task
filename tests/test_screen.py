from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_comparison_failure_and_recovery():
    screen = AppTest.from_file(str(APP), default_timeout=30).run()
    for fixture in ("Clean", "Broken", "Clean"):
        screen.radio[1].set_value(fixture)
        screen.button[0].click().run()
        assert not screen.exception
        if fixture == "Broken":
            assert "missing status" in screen.error[0].value
            assert not screen.metric and not screen.expander and not screen.dataframe
        else:
            assert [metric.value for metric in screen.metric] == [
                "96.4%", "92.0%", "-4.4 pp", "-3.2 pp", "-1.2 pp"]
            assert "SELECT" in screen.code[0].value
            assert screen.dataframe[0].value["Attempt share"].tolist() == [
                "80.0%", "20.0%", "40.0%", "60.0%"]
            assert not screen.error


def test_clarification_and_live_error_replace_metrics(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    screen = AppTest.from_file(str(APP), default_timeout=30).run()
    screen.button[0].click().run()
    assert screen.metric
    screen.text_area[0].set_value("Which bank changed?")
    screen.button[0].click().run()
    assert "sample question" in screen.info[0].value
    assert not screen.metric and not screen.expander
    screen.radio[0].set_value("Live Gemini")
    screen.button[0].click().run()
    assert "GEMINI_API_KEY" in screen.error[0].value
    assert not screen.metric and not screen.expander and not screen.info
