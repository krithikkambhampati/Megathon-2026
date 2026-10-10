import plotly.graph_objects as go
import streamlit as st

from components.common import ESTIMATE_NOTE, flags_with, insufficient, require_analysis, saving_md
from components.explain_box import explain_box
from greenhome import format as F
from labels import FUEL_COLOUR

result = require_analysis()
sv, carbon = result["savings"], result["carbon"]
st.title("Savings & carbon")
st.caption("How much energy and carbon could I save?")
if sv["status"] != "ok":
    what = "savings with this heating fuel" if sv["status"] == "out_of_scope" else "savings"
    insufficient(what, flags_with(result, "INSUFFICIENT_INFO_SAVINGS", "OUT_OF_SCOPE_FUEL"))
    st.stop()

st.write(
    f"For the full recommended package ({len(sv['retrofits'])} retrofits), with their interactions taken "
    "into account."
)
c = st.columns(3)
c[0].metric("Net energy saving", F.fmt_kwh_saving(sv["saving"]["net_kwh"]), help="Electricity + gas bought")
c[1].metric(
    "Improvement potential",
    F.fmt_pct(sv["improvement_potential_pct"]),
    help="How much less energy the home would buy each year",
)
c[2].metric(
    "Carbon reduction",
    F.fmt_tonnes(carbon["total_kg"]) if carbon else F.UNKNOWN,
    help="Calculated fuel by fuel",
)

st.subheader("Before and after, by fuel")
fuels = [("Electricity", "electricity_kwh"), ("Gas", "gas_kwh")]
fig = go.Figure()
for name, opacity, src in (("Now", 0.4, sv["baseline"]), ("After", 1.0, sv["after"])):
    fig.add_bar(
        name=name,
        x=[f for f, _ in fuels],
        y=[src[k] for _, k in fuels],
        opacity=opacity,
        marker_color=[FUEL_COLOUR["electricity"], FUEL_COLOUR["gas"]],
        text=[F.fmt_kwh(src[k]) for _, k in fuels],
        textposition="outside",
    )
fig.update_layout(
    barmode="group",
    height=340,
    margin=dict(l=0, r=0, t=10, b=10),
    showlegend=False,
    yaxis=dict(title="kWh per year"),
)
st.plotly_chart(fig, width="stretch")
st.markdown(
    f"Electricity saving: {saving_md(sv['saving']['electricity_kwh'])} &nbsp;·&nbsp; "
    f"Gas saving: {saving_md(sv['saving']['gas_kwh'])}"
)
if F.round_half_up(sv["saving"]["electricity_kwh"], 10) < 0:
    st.info(
        "**Electricity use goes up while gas use goes down.** A heat pump replaces gas heating with electric "
        "heating, which uses far less energy in total."
    )
st.caption(ESTIMATE_NOTE)
explain_box(result, "savings", "Explain these savings")

if carbon:
    st.subheader("Carbon, fuel by fuel")
    st.markdown(
        "| Fuel | Change | Emission factor |\n|---|---|---|\n"
        f"| Electricity | {saving_md(carbon['electricity_kg'], kg=True)} | "
        f"{carbon['ef_electricity']:g} kg CO2e/kWh |\n"
        f"| Gas | {saving_md(carbon['gas_kg'], kg=True)} | {carbon['ef_gas']:g} kg CO2e/kWh |\n"
        f"| **Total** | **{F.fmt_kg_saving(carbon['total_kg'])}** | |"
    )
    st.caption(f"Source: {carbon['ef_source']}")
