from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[3] / "ui" / "app.py")


def test_app_runs_without_api():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    # API isn't running in tests -> badge must say so instead of crashing
    assert any("API unreachable" in e.value for e in at.sidebar.error)


def test_session_state_initialised():
    at = AppTest.from_file(APP, default_timeout=30).run()
    for key in ["home_input", "analysis", "base_analysis", "scenario", "scenario_analysis",
                "chat_history", "customer_id", "pending_memory"]:
        assert key in at.session_state
    assert at.session_state["chat_history"] == []
