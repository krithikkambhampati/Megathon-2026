"""Streamlit entry point. Run with `make ui`. Thin client: every number comes from the API."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so pages can `import api_client`, `state`, ...

import streamlit as st  # noqa: E402

from components.sidebar import health_badge  # noqa: E402
from state import init_state  # noqa: E402

st.set_page_config(page_title="Green Home Score", page_icon="🏠", layout="wide")
init_state()

PAGES = [
    st.Page("pages/01_Your_home.py", title="Your home", icon="🏠", default=True),
    st.Page("pages/02_Score.py", title="Score", icon="📊"),
    st.Page("pages/03_Problem_areas.py", title="Problem areas", icon="⚠️"),
    st.Page("pages/04_Recommendations.py", title="Recommendations", icon="🛠️"),
    st.Page("pages/05_Savings.py", title="Savings & carbon", icon="⚡"),
    st.Page("pages/06_Value.py", title="Property value", icon="💷"),
    st.Page("pages/07_What_if.py", title="What-if", icon="💬"),
    st.Page("pages/08_Portfolio.py", title="Portfolio", icon="📋"),
    st.Page("pages/09_About.py", title="About & methodology", icon="ℹ️"),
]

nav = st.navigation(PAGES)
health_badge()
nav.run()
