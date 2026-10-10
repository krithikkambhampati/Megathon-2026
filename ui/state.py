"""Session-state keys (roadmap §5.7). Use exactly these; don't add parallel copies under new keys."""

import streamlit as st

DEFAULTS: dict = {
    "home_input": None,  # dict | None  (HomeInput JSON)
    "analysis": None,  # dict | None  (AnalysisResult JSON)
    "base_analysis": None,  # dict | None
    "scenario": None,  # dict | None  (Scenario JSON)
    "scenario_analysis": None,  # dict | None
    "chat_history": [],  # list[dict]
    "customer_id": None,  # str | None
    "pending_memory": None,  # list[dict] | None  (unconfirmed memory proposal)
    "scenario_diff": None,  # dict | None  (ResultDiff JSON: base_analysis vs scenario_analysis)
}


def init_state() -> None:
    for key, default in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = list(default) if isinstance(default, list) else default
