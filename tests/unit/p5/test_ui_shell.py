import sys
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

UI = Path(__file__).resolve().parents[3] / "ui"
APP = str(UI / "app.py")
sys.path.insert(0, str(UI))

import api_client  # noqa: E402  (the same module object the app imports)


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch):
    """Never talk to a real API (one may be running on :8000), and don't reuse cached health."""
    monkeypatch.setattr(api_client, "BASE_URL", "http://127.0.0.1:9")
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def test_app_runs_without_api():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    # API isn't reachable in tests -> badge must say so instead of crashing
    assert any("API unreachable" in e.value for e in at.sidebar.error)


def test_session_state_initialised():
    at = AppTest.from_file(APP, default_timeout=30).run()
    for key in ["home_input", "analysis", "base_analysis", "scenario", "scenario_analysis",
                "chat_history", "customer_id", "pending_memory"]:
        assert key in at.session_state
    assert at.session_state["chat_history"] == []
