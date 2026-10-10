"""'Explain this' box: P4's checked explanation of one section (POST /v1/explain), shown with its badge."""

import streamlit as st

import api_client


def badge(check: dict) -> str:
    if check.get("fallback_used"):
        return "Template answer"
    return f"✓ all {len(check.get('numbers_found', []))} numbers verified"


def explain_box(result: dict, section: str, label: str) -> None:
    """One button per section; the answer is kept per analysis so it survives reruns."""
    key = f"explain::{result['analysis_id']}::{section}"
    if st.button(label, key=f"btn_{key}"):
        try:
            with st.spinner("Writing the explanation…"):
                st.session_state[key] = api_client.explain(result["analysis_id"], section)
        except api_client.APIError as err:
            if err.code == "analysis_not_found":  # API restarted: recompute once, then explain
                try:
                    fresh = api_client.analyse(
                        st.session_state["home_input"], st.session_state.get("customer_id")
                    )
                    st.session_state[key] = api_client.explain(fresh["analysis_id"], section)
                except (api_client.APIError, KeyError) as again:
                    st.error(getattr(again, "message", "Re-run the analysis on Your home, then try again."))
            else:
                st.error(err.message)
    answer = st.session_state.get(key)
    if answer and answer.get("text"):
        with st.container(border=True):
            st.markdown(answer["text"])
            st.caption(badge(answer["check"]))
