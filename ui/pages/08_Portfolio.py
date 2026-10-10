import streamlit as st

import api_client
from components.common import class_chip
from greenhome import format as F
from labels import ISSUE_TEXT, label

st.title("Portfolio")
st.caption(
    "For the lender: homes ranked by improvement potential, the share of bought energy that every "
    "suitable retrofit together could save."
)

poor_only = st.toggle("Poor and Very poor only", key="pf_poor_only")
try:
    p = api_client.portfolio(limit=500, poor_only=poor_only)
except api_client.APIError as err:
    st.info(err.message)
    st.stop()

if p.get("source") == "examples":
    st.info(
        "**Example portfolio:** the demo homes, scored by the real models. Where Part 1's processed data "
        "is available, `make portfolio` ranks the whole held-out test split instead."
    )

c1, c2 = st.columns(2)
c1.metric("Homes listed", f"{p['total']:,}")
c2.metric("Ranking", "Improvement potential")

rows = p["rows"]
if not rows:
    st.write("No homes match.")
    st.stop()
table = {
    "Rank": [r["rank"] for r in rows],
    "Property": [r["property_id"] for r in rows],
    "Type": [label("PropertyType", r["property_type"]) for r in rows],
    "Region": [label("Region", r["region"]) for r in rows],
    "Score": [F.fmt_score(r["score"]) for r in rows],
    "Class": [label("ScoreClass", r["score_class"]) if r["score_class"] else "—" for r in rows],
    "Improvement potential": [F.fmt_pct(r["improvement_potential_pct"]) for r in rows],
    "Key issues": [", ".join(ISSUE_TEXT.get(c, c) for c in r["key_issues"]) or "—" for r in rows],
}
st.dataframe(table, hide_index=True, width="stretch")
st.caption(
    f"Built {p['generated_at']} with models {', '.join(f'{k} {v}' for k, v in p['model_versions'].items())}. "
    "Estimates, not guarantees."
)

st.subheader("Look at one home")
pid = st.selectbox(
    "Property",
    [r["property_id"] for r in rows],
    key="pf_pick",
    format_func=lambda x: next(
        f"{r['property_id']} · {label('PropertyType', r['property_type'])}"
        for r in rows
        if r["property_id"] == x
    ),
)
picked = next(r for r in rows if r["property_id"] == pid)
st.markdown(
    f"Score {F.fmt_score(picked['score'])} &nbsp; {class_chip(picked['score_class'])}", unsafe_allow_html=True
)
if st.button("Open this home", type="primary"):
    try:
        home = api_client.example(pid)
        result = api_client.analyse(home, st.session_state.get("customer_id"))
    except api_client.APIError as err:
        st.error(
            err.message
            if err.code != "example_not_found"
            else "This home's details aren't in the demo set, so it can't be opened here."
        )
    else:
        st.session_state.update(
            home_input=home,
            analysis=result,
            base_analysis=result,
            scenario=None,
            scenario_analysis=None,
            scenario_diff=None,
        )
        st.switch_page("pages/02_Score.py")
