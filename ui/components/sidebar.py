import streamlit as st

import api_client


@st.cache_data(ttl=10, show_spinner=False)
def _health() -> dict | None:
    try:
        return api_client.health()
    except api_client.APIError:
        return None


def health_badge() -> None:
    h = _health()
    if h is None:
        st.sidebar.error(f"API unreachable at {api_client.BASE_URL}")
        return
    text = f"API {h['status']} · models: {h['models_mode']} · LLM: {'on' if h['llm_ok'] else 'off'}"
    (st.sidebar.success if h["status"] == "ok" else st.sidebar.warning)(text)
    st.sidebar.caption(f"Contract {h['contract_version']}")
