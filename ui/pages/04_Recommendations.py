import streamlit as st

from components.common import ESTIMATE_NOTE, chip, flags_with, insufficient, require_analysis, saving_md
from components.explain_box import explain_box
from greenhome import format as F
from labels import REASON_TEXT, label

result = require_analysis()
st.title("Recommendations")
st.caption(
    "Only retrofits that suit this home, in the order to do them. Insulation comes before a heat pump, "
    "because a heat pump works better in a well-insulated home."
)
if result["savings"]["status"] != "ok":
    insufficient("savings", flags_with(result, "INSUFFICIENT_INFO_SAVINGS", "OUT_OF_SCOPE_FUEL"))

recs = result["recommendations"]
ranked = sorted((r for r in recs if r["rank"] is not None), key=lambda r: r["rank"])
other = [r for r in recs if r["rank"] is None]
SUIT = {"high": ("#0d6a50", "#ffffff"), "medium": ("#dcefe7", "#16201c"), "low": ("#eaf0ec", "#5a6a63")}


def fuel_line(name: str, s: dict | None) -> str:
    if not s:
        return f"{name}: —"
    return f"{name}: electricity {saving_md(s['electricity_kwh'])} · gas {saving_md(s['gas_kwh'])}"


if not ranked:
    st.write("No retrofits to recommend yet.")
for r in ranked:
    with st.container(border=True):
        head = f"### {r['rank']}. {label('Retrofit', r['retrofit'])}"
        chips = []
        if r["suitability"]:
            bg, fg = SUIT[r["suitability"]]
            chips.append(chip(f"{label('Suitability', r['suitability'])} suitability", bg, fg))
        if r["feasibility"] == "needs_survey":
            chips.append(chip("Needs a survey", "#fbefd9", "#a86400"))
        st.markdown(head)
        if chips:
            st.markdown(" ".join(chips), unsafe_allow_html=True)
        for code in r["reasons"]:
            st.markdown(f"- {REASON_TEXT.get(code, code)}")
        st.markdown(fuel_line("Saving in this order", r["incremental_saving"]))
        st.markdown(fuel_line("On its own", r["standalone_saving"]))
        st.markdown(f"Typical cost: {F.fmt_range(r['cost_low_gbp'], r['cost_high_gbp'], F.fmt_gbp_cost)}")
        if r["depends_on"]:
            st.caption("Do after: " + ", ".join(label("Retrofit", d) for d in r["depends_on"]))
if ranked:
    st.caption(ESTIMATE_NOTE)
    explain_box(result, "recommendations", "Explain these recommendations")

if other:
    with st.expander(f"Not suitable for this home ({len(other)})"):
        for r in other:
            st.markdown(
                f"**{label('Retrofit', r['retrofit'])}**: "
                + " ".join(REASON_TEXT.get(c, c) for c in r["reasons"])
            )
