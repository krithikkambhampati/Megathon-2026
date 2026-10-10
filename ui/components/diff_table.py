"""ResultDiff → a markdown table.

Every value and change comes from the API (P2's diff_results); this only formats.
"""

import streamlit as st

from greenhome import format as F
from labels import label

ROW_LABEL = {
    "score": "Current score",
    "score_class": "Current class",
    "score_after": "Score after the works",
    "class_after": "Class after the works",
    "electricity_kwh": "Electricity saving",
    "gas_kwh": "Gas saving",
    "net_kwh": "Net energy saving",
    "improvement_potential_pct": "Improvement potential",
    "carbon_total_kg": "Carbon reduction",
    "value_uplift_pct_mid": "Value uplift (middle of range)",
    "rating_after": "EPC rating after",
    "sap_after": "SAP points after",
}
SAVING_UNITS = {"kwh_per_year", "kg_per_year"}


def _value(row: dict, v) -> str:
    unit = row["unit"]
    if v is None:
        return F.UNKNOWN
    if unit == "kwh_per_year":
        text = F.fmt_kwh_saving(v)
    elif unit == "kg_per_year":
        text = F.fmt_kg_saving(v)
    elif unit == "pct":
        text = F.fmt_pct(v)
    elif unit == "score":
        text = F.fmt_score(v)
    elif unit == "sap":
        text = F.fmt_sap(v)
    elif unit == "class":
        text = label("ScoreClass", v)
    else:  # rating
        text = str(v)
    if unit in SAVING_UNITS and F.round_half_up(v, 10) < 0:
        return f":red[{text}]"
    return text


def render(diff: dict, base_title: str = "Recommended plan", new_title: str = "This scenario") -> None:
    rows = [
        r
        for r in diff["rows"]
        # the current score only moves when a scenario changes the home's answers; hide it otherwise
        if not (r["key"] in ("score", "score_class") and r["base"] == r["new"])
    ]
    lines = [f"| | {base_title} | {new_title} | Change |", "|---|---|---|---|"]
    for r in rows:
        if r["delta"] is not None:
            change = F.fmt_delta(r["delta"], r["unit"])
        else:
            change = "changed" if r["base"] != r["new"] else ""
        lines.append(
            f"| {ROW_LABEL.get(r['key'], r['key'])} | {_value(r, r['base'])} | {_value(r, r['new'])} "
            f"| {change} |"
        )
    st.markdown("\n".join(lines))
    if diff.get("retrofits_added"):
        st.caption("Added: " + ", ".join(label("Retrofit", x) for x in diff["retrofits_added"]))
    if diff.get("retrofits_removed"):
        st.caption("Left out: " + ", ".join(label("Retrofit", x) for x in diff["retrofits_removed"]))
