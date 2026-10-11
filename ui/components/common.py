"""Pieces every screen uses.

Display only: numbers arrive from the API and are formatted with greenhome.format.
"""

import html

import streamlit as st

from greenhome import format as F
from labels import CLASS_COLOUR, FLAG_TEXT, label

EPC_COLOUR = {
    "A": "#008054",
    "B": "#19b459",
    "C": "#8dce46",
    "D": "#ffd500",
    "E": "#fcaa65",
    "F": "#ef8023",
    "G": "#e9153b",
}
ESTIMATE_NOTE = "Estimates, not guarantees."


def analysis() -> dict | None:
    return st.session_state.get("analysis")


def require_analysis() -> dict:
    """The current AnalysisResult, or stop the page with a pointer to the Your home screen."""
    result = analysis()
    if result is None:
        st.info("Fill in **Your home** first (or load an example home there) to see this screen.")
        st.page_link("pages/01_Your_home.py", label="Go to Your home", icon="🏠")
        st.stop()
    return result


def chip(text: str, background: str, colour: str = "#14201b") -> str:
    """Inline HTML chip. `text` is escaped; colours are our own constants."""
    return (
        f'<span style="background:{background};color:{colour};border-radius:999px;padding:2px 10px;'
        f'font-weight:700;font-size:0.82rem;white-space:nowrap">{html.escape(text)}</span>'
    )


def class_chip(score_class: str | None) -> str:
    if not score_class:
        return ""
    return chip(label("ScoreClass", score_class), CLASS_COLOUR.get(score_class, "#ccc"))


def epc_chip(rating: str | None) -> str:
    return chip(rating, EPC_COLOUR[rating]) if rating in EPC_COLOUR else chip("—", "#e5e7e6")


def saving_md(x: float | None, kg: bool = False) -> str:
    """Saving as markdown; an increase (negative saving) is shown in red, never as a saving (BUILD_GUIDE §7.1)."""
    text = F.fmt_kg_saving(x) if kg else F.fmt_kwh_saving(x)
    return f":red[**{text}**]" if x is not None and F.round_half_up(x, 10) < 0 else text


def flags_with(result: dict, *codes: str) -> list[dict]:
    return [f for f in result.get("flags", []) if f["code"] in codes]


def insufficient(what: str, flags: list[dict] | None = None) -> None:
    detail = " ".join(f["message"] for f in flags or []) or "Answer more questions on the Your home screen."
    st.warning(f"**Not enough information for {what}.** {detail}")


def flags_panel(flags: list[dict]) -> None:
    if not flags:
        return
    icon = {"error": "⛔", "warning": "⚠️", "info": "ℹ️"}
    with st.container(border=True):
        st.markdown("**What we noticed in your answers**")
        for f in sorted(flags, key=lambda f: {"error": 0, "warning": 1, "info": 2}[f["severity"]]):
            title = FLAG_TEXT.get(f["code"], f["code"])
            st.markdown(f"{icon[f['severity']]} **{title}** · {f['message']}")
