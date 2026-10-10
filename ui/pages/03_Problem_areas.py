import plotly.graph_objects as go
import streamlit as st

from components.common import per_m2, require_analysis
from labels import ISSUE_TEXT, SEVERITY_ORDER, label

result = require_analysis()
st.title("Problem areas")
st.caption("Which parts of the home are holding it back?")
if result.get("is_poor"):
    st.error(
        f"**{label('ScoreClass', result['score']['score_class'])} energy efficiency.** This home is in the "
        "lowest two classes. The issues below are why."
    )

left, right = st.columns(2, gap="large")
with left:
    st.subheader("Key issues")
    issues = sorted(result["issues"], key=lambda i: SEVERITY_ORDER[i["severity"]])
    if not issues:
        st.write(
            "No issues found"
            + (" (not enough information to check)." if result["score"]["status"] != "ok" else ".")
        )
    for i in issues:
        mark = {"high": "🔴", "medium": "🟠", "low": "⚪"}[i["severity"]]
        st.markdown(f"{mark} **{ISSUE_TEXT.get(i['code'], i['code'])}**  \n{i['message']}")

with right:
    st.subheader("Compared with similar homes")
    p = result.get("peer")
    if not p:
        st.write("Not available: we need metered energy use and a floor area to compare fairly.")
    else:
        bands = {
            "lt50": "under 50 m²",
            "50_90": "50–90 m²",
            "90_130": "90–130 m²",
            "130_200": "130–200 m²",
            "gt200": "over 200 m²",
        }
        st.caption(
            "Similar homes: "
            + (label("PropertyType", p["property_type"]).lower() if p["property_type"] else "all types")
            + ", "
            f"{bands[p['floor_area_band']]}. Bigger homes use more in total, so we compare use per m²."
        )
        top = max(p["p90_kwh_m2"] * 1.35, p["intensity_kwh_m2"] * 1.1)  # chart width only
        fig = go.Figure()
        for x0, x1, colour in (
            (0, p["p50_kwh_m2"], "#dcefe7"),
            (p["p50_kwh_m2"], p["p75_kwh_m2"], "#eaf0ec"),
            (p["p75_kwh_m2"], p["p90_kwh_m2"], "#fbefd9"),
            (p["p90_kwh_m2"], top, "#f9e1dd"),
        ):
            fig.add_shape(type="rect", x0=x0, x1=x1, y0=0, y1=1, fillcolor=colour, line_width=0)
        for v, name in (
            (p["p50_kwh_m2"], "typical"),
            (p["p75_kwh_m2"], "top 25%"),
            (p["p90_kwh_m2"], "top 10%"),
        ):
            fig.add_vline(
                x=v,
                line_width=1,
                line_color="gray",
                annotation_text=f"{name}<br>{per_m2(v)}",
                annotation_position="bottom",
            )
        fig.add_vline(
            x=p["intensity_kwh_m2"],
            line_width=3,
            line_color="#16201c",
            annotation_text=f"you {per_m2(p['intensity_kwh_m2'])}",
            annotation_position="top",
        )
        fig.update_layout(
            height=170,
            margin=dict(l=10, r=10, t=30, b=50),
            xaxis=dict(range=[0, top], title="kWh per m² per year"),
            yaxis=dict(visible=False, range=[0, 1]),
            showlegend=False,
        )
        st.plotly_chart(fig, width="stretch")
