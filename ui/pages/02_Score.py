import plotly.graph_objects as go
import streamlit as st

import api_client
from components.common import class_chip, flags_with, insufficient, require_analysis
from greenhome import format as F
from labels import CLASS_COLOUR, SCORE_COMPONENT, label

result = require_analysis()
s = result["score"]
st.title("Green Home Score")
st.caption("How green is my home today?")
if s["status"] != "ok":
    insufficient("a score", flags_with(result, "INSUFFICIENT_INFO_SCORE"))
    st.stop()


@st.cache_data(ttl=300, show_spinner=False)
def methodology() -> dict | None:
    try:
        return api_client.methodology()
    except api_client.APIError:
        return None


m = methodology()
left, right = st.columns([1, 2], gap="large")
with left:
    st.markdown(
        f'<div style="font-size:4.8rem;font-weight:700;line-height:1">{F.fmt_score(s["score"])}'
        f'<span style="font-size:1.3rem;color:gray"> /100</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(class_chip(s["score_class"]), unsafe_allow_html=True)
    unknown = len(flags_with(result, "MISSING_FIELD"))
    rng = s.get("score_range")
    if rng and rng[0] != rng[1]:
        st.caption(
            f"Could be {F.fmt_range(rng[0], rng[1], F.fmt_score)}, because {unknown} "
            f"answer{'s are' if unknown != 1 else ' is'} unknown."
        )
    elif unknown:
        st.caption(
            f"{unknown} answer{'s were' if unknown != 1 else ' was'} unknown; the estimate used doesn't "
            "change the score."
        )
with right:
    if m:
        classes = m["classes"]  # highest first
        rows = []
        for i, c in enumerate(classes):
            top = 100 if i == 0 else classes[i - 1]["min"] - 1
            here = c["class"] == s["score_class"]
            bar_style = (
                f"width:{40 + i * 12}%;background:{CLASS_COLOUR[c['class']]};border-radius:3px 11px 11px 3px;"
                "padding:2px 8px;font-weight:700;font-size:0.8rem;color:#14201b;"
                + ("outline:2px solid currentColor;" if here else "")
            )
            tag_style = "font-size:0.85rem;" + ("font-weight:700" if here else "opacity:.7")
            tag = label("ScoreClass", c["class"]) + (" ◀ you" if here else "")
            rows.append(
                f'<div style="display:flex;gap:10px;align-items:center;margin:2px 0">'
                f'<div style="{bar_style}">{c["min"]}–{top}</div><span style="{tag_style}">{tag}</span></div>'
            )
        st.markdown("".join(rows), unsafe_allow_html=True)

st.subheader("Why this score")
st.caption(
    "Each bar is one component: its weight × its 0–100 sub-score. The faint bar is the most it could add."
)
comps = s["components"][::-1]
names = [SCORE_COMPONENT[c["key"]] for c in comps]
fig = go.Figure()
fig.add_bar(
    y=names,
    x=[c["weight"] * 100 for c in comps],
    orientation="h",
    marker_color="rgba(13,106,80,0.15)",
    hoverinfo="skip",
    showlegend=False,
)
fig.add_bar(
    y=names,
    x=[c["contribution"] for c in comps],
    orientation="h",
    marker_color="#0d6a50",
    text=[f"{F.fmt_points(c['contribution'])} of {c['weight']:.0%}" for c in comps],
    textposition="outside",
    customdata=[F.fmt_points(c["sub_score"]) for c in comps],
    hovertemplate="%{y}<br>sub-score %{customdata}<extra></extra>",
    showlegend=False,
)
fig.update_layout(
    barmode="overlay",
    height=330,
    margin=dict(l=0, r=40, t=10, b=10),
    xaxis=dict(title="points", range=[0, 30]),
    yaxis=dict(automargin=True),
)
st.plotly_chart(fig, width="stretch")
st.caption(f"Contributions add up to {F.fmt_points(s['score_raw'])}, rounded to {F.fmt_score(s['score'])}.")

after = result.get("score_after")
if after and after.get("score") is not None:
    with st.container(border=True):
        st.markdown(
            f"**After the recommended package:** {F.fmt_score(s['score'])} → {F.fmt_score(after['score'])} "
            f"&nbsp; {class_chip(after['score_class'])}",
            unsafe_allow_html=True,
        )
        st.caption("If every recommended retrofit were installed. See Recommendations for the list.")

with st.expander("How is this computed?"):
    if not m:
        st.write("Methodology unavailable: the API didn't answer.")
    else:
        st.markdown(
            "Score = Σ weight × sub-score. The weights are fixed by the problem statement, and a better "
            "state never gives a lower sub-score."
        )
        b = m["intensity_bounds"]
        st.markdown(
            f"**Energy use per m²:** 100 at or below {b['i_best']:g} kWh/m², 0 at or above "
            f"{b['i_worst']:g}, straight line between."
        )
        enums = {
            "energy_efficiency": "EnergyRating",
            "heating": "HeatingSystem",
            "glazing": "Glazing",
            "renewables": "Renewables",
            "smart_controls": "SmartControls",
        }
        cols = st.columns(2)
        for i, (k, enum) in enumerate(enums.items()):
            with cols[i % 2]:
                st.markdown(f"**{SCORE_COMPONENT[k]}**")
                st.table(
                    {
                        "Answer": [label(enum, v) for v in m["sub_score_tables"][k]],
                        "Sub-score": [f"{x:g}" for x in m["sub_score_tables"][k].values()],
                    }
                )
