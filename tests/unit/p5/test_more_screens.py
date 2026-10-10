"""Property value, About & methodology, and the 'Explain this' boxes (AppTest, API faked)."""

import json
import sys
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[3]
UI, FIXTURES = ROOT / "ui", ROOT / "tests" / "fixtures"
sys.path.insert(0, str(UI))

import api_client  # noqa: E402

PIDS = ["P10001", "P90002", "P90003", "P90004", "P90005"]
CHECK_OK = {
    "passed": True,
    "numbers_found": ["32", "100"],
    "unsupported": [],
    "banned_phrases": [],
    "attempts": 1,
    "fallback_used": False,
}


def fixture(pid: str) -> dict:
    return json.loads((FIXTURES / f"analysis_result_{pid}.json").read_text())


def page(name: str) -> str:
    return str(next((UI / "pages").glob(f"{name}*.py")))


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch):
    monkeypatch.setattr(api_client, "BASE_URL", "http://127.0.0.1:9")
    st.cache_data.clear()


def run(name: str, analysis: dict | None = None, **state) -> AppTest:
    at = AppTest.from_file(page(name), default_timeout=60)
    if analysis is not None:
        at.session_state["analysis"] = analysis
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def everything(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [w.value for w in at.warning]
    parts += [str(m.value) for m in at.metric] + [s.value for s in at.subheader] + [i.value for i in at.info]
    return "\n".join(parts)


# ---------- Property value ----------
@pytest.mark.parametrize("pid", PIDS)
def test_value_screen_renders_for_every_fixture(pid):
    at = run("06_", fixture(pid))
    assert not at.exception, at.exception


def test_value_screen_shows_range_and_caveat():
    r = fixture("P10001")
    t = everything(run("06_", r))
    assert "Indicative, not causal" in t
    assert "Potential value:" in t and "£" in t
    assert "your estimate" in t  # P10001's value was given by the user


def test_value_screen_insufficient():
    t = everything(run("06_", fixture("P90003")))
    assert "Not enough information for a value estimate" in t


# ---------- Explain boxes ----------
@pytest.mark.parametrize(
    "name,button,section",
    [
        ("02_", "Explain my score", "score"),
        ("04_", "Explain these recommendations", "recommendations"),
        ("05_", "Explain these savings", "savings"),
        ("06_", "Explain this estimate", "value"),
    ],
)
def test_explain_buttons_show_text_and_badge(monkeypatch, name, button, section):
    calls = []

    def explain(analysis_id, sec):
        calls.append((analysis_id, sec))
        return {"text": f"Here is the {sec} explanation.", "check": CHECK_OK}

    monkeypatch.setattr(api_client, "explain", explain)
    r = fixture("P10001")
    at = run(name, r)
    next(b for b in at.button if b.label == button).click().run()
    assert not at.exception, at.exception
    assert calls == [(r["analysis_id"], section)]
    t = everything(at)
    assert f"Here is the {section} explanation." in t and "✓ all 2 numbers verified" in t


def test_explain_reanalyses_once_after_an_api_restart(monkeypatch):
    r, fresh = fixture("P10001"), fixture("P10001") | {"analysis_id": "fresh-id"}
    seen = []

    def explain(analysis_id, sec):
        seen.append(analysis_id)
        if analysis_id == r["analysis_id"]:
            raise api_client.APIError(404, "analysis_not_found", "No cached analysis")
        return {"text": "ok after re-analysis", "check": CHECK_OK | {"fallback_used": True}}

    monkeypatch.setattr(api_client, "explain", explain)
    monkeypatch.setattr(api_client, "analyse", lambda home, customer_id=None: fresh)
    at = run("02_", r, home_input={"property_id": "P10001"})
    next(b for b in at.button if b.label == "Explain my score").click().run()
    assert seen == [r["analysis_id"], "fresh-id"]
    t = everything(at)
    assert "ok after re-analysis" in t and "Template answer" in t


# ---------- About & methodology ----------
def test_about_screen(monkeypatch):
    health = {
        "status": "degraded",
        "contract_version": "1.1.0",
        "models_mode": "real",
        "llm_ok": False,
        "model_versions": {"energy": "e1", "rating": "r1", "recommender": "m1", "value": "v1"},
    }
    meth = {
        "contract_version": "1.1.0",
        "score_method_version": "score-v1",
        "weights": {
            "energy_efficiency": 0.25,
            "consumption_intensity": 0.2,
            "insulation": 0.15,
            "heating": 0.15,
            "glazing": 0.1,
            "renewables": 0.1,
            "smart_controls": 0.05,
        },
        "classes": [{"class": "highly_efficient", "min": 80}, {"class": "very_poor", "min": 0}],
        "sub_score_tables": {},
        "intensity_bounds": {"i_best": 85.0, "i_worst": 230.0},
        "retrofit_catalogue": [],
        "model_versions": {},
        "emission_factors": [
            {"fuel": "electricity", "kg_co2e_per_kwh": 0.13096, "source": "DESNZ 2026"},
            {"fuel": "gas", "kg_co2e_per_kwh": 0.18231, "source": "DESNZ 2026"},
        ],
    }
    monkeypatch.setattr(api_client, "health", lambda: health)
    monkeypatch.setattr(api_client, "methodology", lambda: meth)
    at = run("09_")
    assert not at.exception, at.exception
    t = everything(at)
    assert "0.13096 kg CO2e" in t and "Limitations" in t
    assert any("trained models" in str(tbl.value) for tbl in at.table)


def test_about_screen_api_down():
    at = run("09_")  # BASE_URL points nowhere
    assert not at.exception
    assert at.error
