"""Screens 1–5 rendered with Streamlit's AppTest against P2's fixture results (no API needed)."""

import json
import sys
from datetime import date
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[3]
UI, FIXTURES = ROOT / "ui", ROOT / "tests" / "fixtures"
sys.path.insert(0, str(UI))

import api_client  # noqa: E402
from components import home_form  # noqa: E402


def fixture(pid: str) -> dict:
    return json.loads((FIXTURES / f"analysis_result_{pid}.json").read_text())


def home(pid: str) -> dict:
    return json.loads((FIXTURES / f"home_input_{pid}.json").read_text())


def page(name: str) -> str:
    return str(next((UI / "pages").glob(f"{name}*.py")))


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch):
    monkeypatch.setattr(api_client, "BASE_URL", "http://127.0.0.1:9")
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def run(name: str, analysis: dict | None = None) -> AppTest:
    at = AppTest.from_file(page(name), default_timeout=30)
    if analysis is not None:
        at.session_state["analysis"] = analysis
    return at.run()


def text(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [t.value for t in at.title]
    parts += [x.value for x in at.warning] + [x.value for x in at.info] + [x.value for x in at.error]
    parts += [str(m.value) for m in at.metric]
    return "\n".join(parts)


# ---------- form conversion (pure) ----------
def test_blank_answers_become_none():
    values = {"property_type": "flat", "glazing": None, "floor_area_m2": None, "bedrooms": 2, "region": ""}
    h = home_form.build_home_input(values, "Not sure", {}, [])
    assert h["property_type"] == "flat" and h["bedrooms"] == 2
    assert h["glazing"] is None and h["floor_area_m2"] is None and h["region"] is None
    assert h["energy"] == {}
    assert not any(v in ("", "unknown", 0) for k, v in h.items() if k != "bedrooms")


def test_monthly_rows_keep_gaps_and_drop_empty_rows():
    rows = [
        {"month": "2025-01", "electricity_kwh": 400.0, "gas_kwh": float("nan")},
        {"month": "2025-02", "electricity_kwh": None, "gas_kwh": None},
        {"month": "2025-03", "electricity_kwh": None, "gas_kwh": 900},
    ]
    h = home_form.build_home_input({}, "Monthly readings", {}, rows)
    assert h["energy"]["monthly"] == [
        {"month": "2025-01", "electricity_kwh": 400.0, "gas_kwh": None},
        {"month": "2025-03", "electricity_kwh": None, "gas_kwh": 900.0},
    ]


def test_annual_and_ids():
    h = home_form.build_home_input(
        {},
        "Yearly totals",
        {"annual_electricity_kwh": 4800, "annual_gas_kwh": None},
        [],
        {"property_id": "P10001", "customer_id": None},
    )
    assert h["energy"] == {"annual_electricity_kwh": 4800.0, "annual_gas_kwh": None}
    assert h["property_id"] == "P10001"


def test_last_12_months():
    assert home_form.last_12_months(date(2026, 3, 15)) == [f"2025-{m:02d}" for m in range(3, 13)] + [
        "2026-01",
        "2026-02",
    ]


def test_built_input_is_valid_for_the_contract():
    from greenhome.contracts import HomeInput

    src = home("P90004")
    rows = src["energy"]["monthly"]
    values = {f: src.get(f) for f, *_ in home_form.FIELDS}
    HomeInput.model_validate(home_form.build_home_input(values, "Monthly readings", {}, rows))


# ---------- screens ----------
@pytest.mark.parametrize("name", ["02_", "03_", "04_", "05_"])
@pytest.mark.parametrize("pid", ["P10001", "P90002", "P90003", "P90004", "P90005"])
def test_screens_render_for_every_fixture(name, pid):
    at = run(name, fixture(pid))
    assert not at.exception, at.exception


def test_score_screen_p10001():
    r = fixture("P10001")
    at = run("02_", r)
    t = text(at)
    assert f"{r['score']['score']}<span" in t  # the big number, from the API
    assert "Poor" in t
    assert "After the recommended package" in t


def test_score_insufficient():
    t = text(run("02_", fixture("P90003")))
    assert "Not enough information for a score" in t


def test_problem_areas_p10001():
    t = text(run("03_", fixture("P10001")))
    assert "Poor energy efficiency" in t
    assert "Single glazing" in t and "Uninsulated walls" in t


def test_recommendations_heat_pump_shows_electricity_increase_in_red():
    t = text(run("04_", fixture("P10001")))
    assert "Air source heat pump" in t
    assert ":red[**" in t and "increase**]" in t
    assert "Not suitable" not in t or "Solid wall insulation" in t


def test_savings_p10001():
    at = run("05_", fixture("P10001"))
    t = text(at)
    assert "Electricity use goes up while gas use goes down" in t
    assert "Estimates, not guarantees." in t
    assert "t CO2e/year" in t


def test_savings_out_of_scope_for_off_gas_home():
    t = text(run("05_", fixture("P90005")))
    assert "Not enough information for savings with this heating fuel" in t


def test_screen_without_analysis_points_to_your_home():
    at = AppTest.from_file(str(UI / "app.py"), default_timeout=30)
    at.run()
    at.switch_page("pages/02_Score.py").run()
    assert not at.exception
    assert any("Fill in **Your home** first" in i.value for i in at.info)


def test_your_home_load_example_and_analyse(monkeypatch):
    monkeypatch.setattr(
        api_client,
        "examples",
        lambda: [{"property_id": "P10001", "title": "PS example home", "why_interesting": "x"}],
    )
    monkeypatch.setattr(api_client, "example", lambda pid: home(pid))
    sent = []

    def fake_analyse(h, customer_id=None):
        sent.append(h)
        return fixture("P10001")

    monkeypatch.setattr(api_client, "analyse", fake_analyse)
    at = AppTest.from_file(str(UI / "app.py"), default_timeout=30).run()  # Your home is the default page
    at.selectbox(key="example_choice").select("P10001").run()
    at.button[0].click().run()  # Load example
    assert at.selectbox(key="f_glazing").value == "single"
    next(b for b in at.button if b.label == "Analyse my home").click().run()
    assert not at.exception, at.exception
    assert sent and sent[0]["glazing"] == "single" and sent[0]["energy"]["annual_gas_kwh"] == 12000.0
    assert at.session_state["analysis"]["analysis_id"] == fixture("P10001")["analysis_id"]
    assert "Green Home Score" in text(at)
