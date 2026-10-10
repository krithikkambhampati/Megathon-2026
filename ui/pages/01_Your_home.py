import streamlit as st

import api_client
from components import home_form
from components.common import class_chip, flags_panel
from greenhome import format as F
from labels import label

st.title("Your home")
st.caption("Every question has a “Not sure” option. Unknown answers are sent as unknown, never guessed.")

try:
    items = api_client.examples()
except api_client.APIError as err:
    items = []
    st.warning(f"Couldn't load example homes: {err.message}")
if items:
    titles = {
        i["property_id"]: f"{i['title']}{' · synthetic demo' if i.get('synthetic') else ''}" for i in items
    }
    c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
    choice = c1.selectbox(
        "Start from an example home",
        [None, *titles],
        key="example_choice",
        format_func=lambda v: "Choose an example…" if v is None else titles[v],
    )
    if c2.button("Load example", disabled=choice is None, width="stretch"):
        try:
            home_form.load_into_state(api_client.example(choice))
            st.rerun()
        except api_client.APIError as err:
            st.error(err.message)

home = home_form.render()
if home is not None:
    try:
        with st.spinner("Analysing…"):
            result = api_client.analyse(home, st.session_state.get("customer_id"))
    except api_client.APIError as err:
        st.error(err.message)
        st.stop()
    st.session_state.update(
        home_input=home, analysis=result, base_analysis=result, scenario=None, scenario_analysis=None
    )

result = st.session_state.get("analysis")
if result:
    st.divider()
    s = result["score"]
    if s["status"] == "ok":
        st.markdown(
            f"### Green Home Score: {F.fmt_score(s['score'])}/100 &nbsp; {class_chip(s['score_class'])}",
            unsafe_allow_html=True,
        )
    else:
        st.markdown("### Not enough information for a score yet")
    c = st.columns(4)
    c[0].page_link("pages/02_Score.py", label="Why this score", icon="📊")
    c[1].page_link("pages/03_Problem_areas.py", label="Problem areas", icon="⚠️")
    c[2].page_link("pages/04_Recommendations.py", label="Recommendations", icon="🛠️")
    c[3].page_link("pages/05_Savings.py", label="Savings & carbon", icon="⚡")
    flags_panel(result["flags"])
    estimated = {f: p for f, p in result["home"]["provenance"].items() if p in ("imputed", "assumed")}
    if estimated:
        with st.expander(f"Answers we estimated ({len(estimated)})"):
            for field, prov in estimated.items():
                st.markdown(f"- **{field.replace('_', ' ')}**: {label('Provenance', prov)}")
