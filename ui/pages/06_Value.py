import plotly.graph_objects as go
import streamlit as st

from components.common import epc_chip, flags_with, insufficient, require_analysis
from components.explain_box import explain_box
from greenhome import format as F

result = require_analysis()
v = result["value"]
st.title("Property value")
st.caption("Could the recommended retrofits raise the property's value?")
if v["status"] != "ok":
    insufficient("a value estimate", flags_with(result, "INSUFFICIENT_INFO_VALUE"))
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric(
    "Value today",
    F.fmt_gbp_value(v["current_value_gbp"]),
    help="Your estimate" if v["current_value_source"] == "user" else "Model estimate",
)
c1.caption("your estimate" if v["current_value_source"] == "user" else "model estimate")
c2.markdown("**EPC rating**")
c2.markdown(f"{epc_chip(v['rating_before'])} → {epc_chip(v['rating_after'])}", unsafe_allow_html=True)
c2.caption(f"SAP {F.fmt_sap(v['sap_before'])} → {F.fmt_sap(v['sap_after'])}")
c3.metric(
    "Indicative uplift",
    F.fmt_range(v["uplift_pct_low"], v["uplift_pct_high"]),
    help="A range from 20 bootstrap models, never a single number",
)

st.subheader(f"Potential value: {F.fmt_range(v['value_low_gbp'], v['value_high_gbp'], F.fmt_gbp_value)}")
now, lo, hi = v["current_value_gbp"], v["value_low_gbp"], v["value_high_gbp"]
pad = (max(hi, now) - min(lo, now)) * 0.6 or now * 0.01  # chart margins only
fig = go.Figure()
fig.add_shape(type="rect", x0=lo, x1=hi, y0=0.35, y1=0.65, fillcolor="#0d6a50", opacity=0.8, line_width=0)
fig.add_vline(
    x=now,
    line_width=3,
    line_color="#16201c",
    annotation_text=f"today {F.fmt_gbp_value(now)}",
    annotation_position="top",
)
fig.add_annotation(x=lo, y=0.2, text=F.fmt_gbp_value(lo), showarrow=False)
fig.add_annotation(x=hi, y=0.2, text=F.fmt_gbp_value(hi), showarrow=False)
fig.update_layout(
    height=170,
    margin=dict(l=10, r=10, t=30, b=10),
    showlegend=False,
    xaxis=dict(range=[min(lo, now) - pad, max(hi, now) + pad], showticklabels=False),
    yaxis=dict(visible=False, range=[0, 1]),
)
st.plotly_chart(fig, width="stretch")

st.warning(
    "**Indicative, not causal.** Based on how sale prices relate to EPC ratings in real past sales, "
    "holding location, size, property type and market conditions constant. It is not a guarantee: "
    "better-rated homes can differ in ways the data doesn't capture, such as condition."
)
explain_box(result, "value", "Explain this estimate")
