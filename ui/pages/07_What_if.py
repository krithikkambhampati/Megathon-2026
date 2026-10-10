import uuid

import streamlit as st

import api_client
from components import diff_table
from components.common import ESTIMATE_NOTE, require_analysis
from labels import REASON_TEXT, label

result = require_analysis()
base = st.session_state.get("base_analysis") or result
home = st.session_state.get("home_input")
st.title("What-if")
st.caption(
    "Pick a different set of retrofits, or ask a question. The models rerun first; explanations only "
    "describe those results."
)
if home is None:
    st.info("Analyse a home on **Your home** first.")
    st.stop()

feasible = [r["retrofit"] for r in base["recommendations"] if r["feasibility"] != "infeasible"]
plan = list(base["savings"]["retrofits"])


def tkey(r: str) -> str:
    return f"t_{r}"


# A chat answer may set a new scenario: apply it to the toggles before they are drawn.
pending = st.session_state.pop("toggle_sync", None)
for r in feasible:
    if pending is not None:
        st.session_state[tkey(r)] = r in pending
    st.session_state.setdefault(tkey(r), r in plan)


def run_scenario(retrofits: list[str]) -> None:
    scenario = {"name": "custom", "mode": "custom" if retrofits else "none", "retrofits": retrofits}
    try:
        with st.spinner("Rerunning the models…"):
            res = api_client.scenario(home, scenario, st.session_state.get("customer_id"))
            diff = api_client.diff(base["analysis_id"], res["analysis_id"])
    except api_client.APIError as err:
        st.error(err.message)
        return
    st.session_state.update(scenario=res["scenario"], scenario_analysis=res, scenario_diff=diff)


def badge(check: dict) -> str:
    if check.get("fallback_used"):
        return "Template answer"
    return f"✓ all {len(check.get('numbers_found', []))} numbers verified"


tab_toggles, tab_chat = st.tabs(["Choose retrofits", "Ask a question"])

with tab_toggles:
    if base["savings"]["status"] != "ok" or not feasible:
        st.warning("What-if scenarios need a savings estimate, which isn't available for this home yet.")
    else:
        cols = st.columns(3)
        for i, r in enumerate(feasible):
            cols[i % 3].checkbox(label("Retrofit", r), key=tkey(r))
        chosen = [r for r in feasible if st.session_state[tkey(r)]]
        c1, c2, c3 = st.columns(3)
        if c1.button("Run this scenario", type="primary", width="stretch"):
            run_scenario(chosen)
        if c2.button("Reset to the recommended plan", width="stretch"):
            st.session_state["toggle_sync"] = plan
            st.session_state.update(scenario=None, scenario_analysis=None, scenario_diff=None)
            st.rerun()
        if c3.button(
            "Explain this scenario",
            width="stretch",
            disabled=st.session_state.get("scenario_analysis") is None,
        ):
            try:
                with st.spinner("Writing the explanation…"):
                    ex = api_client.explain(st.session_state["scenario_analysis"]["analysis_id"], "savings")
                st.session_state["scenario_explanation"] = ex
            except api_client.APIError as err:
                st.error(err.message)

    sa, diff = st.session_state.get("scenario_analysis"), st.session_state.get("scenario_diff")
    if sa and diff:
        st.subheader("This scenario compared with the recommended plan")
        diff_table.render(diff)
        for rej in sa.get("rejected", []):
            reason = REASON_TEXT.get(rej["reason"], rej["reason"])
            st.warning(f"**{label('Retrofit', rej['retrofit'])}** left out: {reason}")
        ex = st.session_state.get("scenario_explanation")
        if ex and ex.get("text"):
            with st.container(border=True):
                st.markdown(ex["text"])
                st.caption(badge(ex["check"]))
        st.caption(ESTIMATE_NOTE)

with tab_chat:
    st.session_state.setdefault("chat_session_id", uuid.uuid4().hex)
    if not st.session_state["chat_history"]:
        st.caption(
            'Try: "What if I only install solar panels?", "everything except the heat pump", '
            '"why is my score so low?"'
        )
    for turn in st.session_state["chat_history"]:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
            if turn.get("diff"):
                with st.expander("What changed"):
                    diff_table.render(turn["diff"])
            if turn.get("badge"):
                st.caption(turn["badge"])
    if turn_memory := st.session_state.get("pending_memory"):
        st.info(
            "The assistant noticed something worth remembering about your home, but saving it isn't "
            f"available in this version ({len(turn_memory)} item(s))."
        )

    message = st.chat_input("Ask a what-if question or why something is the way it is")
    if message:
        request = {
            "session_id": st.session_state["chat_session_id"],
            "home": home,
            "message": message,
            "current_scenario": st.session_state.get("scenario"),
            "customer_id": st.session_state.get("customer_id"),
        }
        st.session_state["chat_history"].append({"role": "user", "content": message})
        try:
            with st.spinner("Thinking…"):
                resp = api_client.chat(request)
        except api_client.APIError as err:
            st.session_state["chat_history"].append({"role": "assistant", "content": err.message})
        else:
            st.session_state["chat_history"].append(
                {
                    "role": "assistant",
                    "content": resp["answer"],
                    "badge": badge(resp["check"]),
                    "diff": resp.get("diff"),
                }
            )
            if resp.get("scenario") and resp.get("result"):
                st.session_state.update(
                    scenario=resp["scenario"],
                    scenario_analysis=resp["result"],
                    scenario_diff=resp.get("diff"),
                    scenario_explanation=None,
                )
                st.session_state["toggle_sync"] = resp["scenario"].get("retrofits") or []
            st.session_state["pending_memory"] = resp.get("memory_proposal")
        st.rerun()
