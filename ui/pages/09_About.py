import streamlit as st

import api_client
from labels import SCORE_COMPONENT, label

st.title("About & methodology")
st.markdown(
    "**The core rule:** every number comes from a documented model or formula. The language model only "
    "explains numbers the engine has already computed, and a checker verifies every number it writes."
)

try:
    health = api_client.health()
    m = api_client.methodology()
except api_client.APIError as err:
    st.error(err.message)
    st.stop()

st.subheader("What's running")
mode = {
    "real": "trained models",
    "stub": "stand-in models",
    "fixture": "saved test results",
    "none": "not loaded",
}
st.table(
    {
        "Part": ["Engine contract", "Models", "Model versions", "Explanations"],
        "Status": [
            health["contract_version"],
            mode.get(health["models_mode"], health["models_mode"]),
            ", ".join(f"{k} {v}" for k, v in health["model_versions"].items()) or "—",
            "local language model, checked" if health["llm_ok"] else "template answers (language model off)",
        ],
    }
)

st.subheader("Data")
st.markdown(
    "| What | Source | Real or synthetic |\n|---|---|---|\n"
    "| Home features, EPC ratings, SAP points "
    "| EPC register (England & Wales, 11 local authorities) | Real |\n"
    "| Retrofit relevance | EPC assessor recommendations | Real |\n"
    "| Sale prices | HM Land Registry Price Paid, joined to EPCs | Real |\n"
    "| Market index | UK House Price Index | Real |\n"
    "| Monthly electricity and gas per home | No public source: generated, calibrated to NEED "
    "| Synthetic |\n"
    "| Energy after retrofits | Physics simulator with hidden household factors | Synthetic |"
)
st.caption(
    "Agreement with synthetic targets doesn't prove real-world accuracy; where real evidence exists the "
    "models are compared with it (NEED observed savings, repeat-EPC rating changes, real sale prices)."
)

st.subheader("Models")
st.markdown(
    "| Model | Predicts | Trained on |\n|---|---|---|\n"
    "| Rating | EPC SAP points now and after retrofits | 2.9M real EPC certificates |\n"
    "| Energy | Electricity and gas after a retrofit package "
    "| Simulated outcomes with hidden household factors |\n"
    "| Recommender | Whether an EPC assessor would recommend each retrofit | 9.4M real assessor labels |\n"
    "| Value | Price at a rating, as a range from 20 models | 618k real sales |"
)

st.subheader("Green Home Score")
left, right = st.columns(2)
with left:
    st.table(
        {
            "Component": [SCORE_COMPONENT[k] for k in m["weights"]],
            "Weight": [f"{w:.0%}" for w in m["weights"].values()],
        }
    )
with right:
    st.table(
        {
            "Class": [label("ScoreClass", c["class"]) for c in m["classes"]],
            "From score": [c["min"] for c in m["classes"]],
        }
    )
b = m["intensity_bounds"]
st.caption(
    f"Energy use per m²: 100 at or below {b['i_best']:g} kWh/m², 0 at or above {b['i_worst']:g}. "
    f"Method {m['score_method_version']}."
)

st.subheader("Carbon")
for ef in m["emission_factors"]:
    st.markdown(
        f"**{'Gas' if ef['fuel'] == 'gas' else 'Electricity'}:** {ef['kg_co2e_per_kwh']:g} kg CO2e "
        f"per kWh · {ef['source']}"
    )

res = m.get("results")
if res:
    st.subheader("Evaluation results")
    st.markdown("**Models** (held-out test homes, compared with a simple baseline)")
    st.table(
        {
            "Model": [r["model"] for r in res["models"]],
            "Measure": [r["metric"] for r in res["models"]],
            "Result": [r["value"] for r in res["models"]],
            "Baseline": [r["baseline"] for r in res["models"]],
        }
    )
    llm = res["llm"]
    st.markdown(f"**Explanations** ({llm['scenarios']} test questions, {llm['model']})")
    st.table(
        {
            "Measure": [r["metric"] for r in llm["rows"]],
            "Result": [r["value"] for r in llm["rows"]],
            "Target": [r["target"] for r in llm["rows"]],
        }
    )
    st.caption(f"Sources: reports/evaluation.md, {llm['source']}.")

st.subheader("Limitations")
st.markdown(
    "- Savings are estimates for electricity and mains gas only; oil, LPG and solid-fuel homes get a score "
    "but no savings.\n"
    "- England and Wales only (EPC coverage). The sample is city-heavy.\n"
    "- Monthly energy and post-retrofit outcomes are synthetic, calibrated to national statistics.\n"
    "- Property value changes are associations from past sales, not proof that a retrofit causes a rise.\n"
    "- Estimates, not guarantees, and not financial advice. Get a professional survey before building work."
)
