"""Problem Statement §11 scenario tests, end to end through the HTTP API (roadmap P5-34).

Organisers may test: missing or conflicting property data, infeasible or interacting retrofits, increased
electricity after a heating-system change, and too little information to estimate savings or value.
Each test uses a committed demo home (P1) or test home (P2) chosen for that case.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def home(pid: str) -> dict:
    for path in (
        ROOT / "data" / "examples" / f"{pid}.json",
        ROOT / "tests" / "fixtures" / f"home_input_{pid}.json",
    ):
        if path.exists():
            return json.loads(path.read_text())
    pytest.skip(f"demo home {pid} not on this machine")


@pytest.fixture(scope="module")
def api():
    mp = pytest.MonkeyPatch()
    mp.setenv("GREENHOME_ENGINE_MODE", "engine")
    with TestClient(create_app()) as c:
        yield c
    mp.undo()


def analyse(api, pid: str) -> dict:
    r = api.post("/v1/analyse", json={"home": home(pid)})
    assert r.status_code == 200, r.text
    return r.json()


def scenario(api, pid: str, retrofits: list[str]) -> dict:
    sc = {"name": "test", "mode": "custom" if retrofits else "none", "retrofits": retrofits}
    r = api.post("/v1/scenario", json={"home": home(pid), "scenario": sc})
    assert r.status_code == 200, r.text
    return r.json()


def explain(api, result: dict, section: str) -> str:
    r = api.post("/v1/explain", json={"analysis_id": result["analysis_id"], "section": section})
    assert r.status_code == 200, r.text
    return r.json()["text"]


def flags(result: dict) -> set[str]:
    return {f["code"] for f in result["flags"]}


def rec(result: dict, retrofit: str) -> dict:
    return next(x for x in result["recommendations"] if x["retrofit"] == retrofit)


# ---------- missing data ----------
def test_almost_no_information_says_insufficient_with_no_numbers(api):
    r = analyse(api, "P1000205_minimal")
    assert r["score"]["status"] == "insufficient" and r["score"]["score"] is None
    assert r["savings"]["status"] == "insufficient" and r["savings"]["saving"] is None
    assert r["value"]["status"] == "insufficient" and r["value"]["value_low_gbp"] is None
    assert {"INSUFFICIENT_INFO_SCORE", "INSUFFICIENT_INFO_SAVINGS", "INSUFFICIENT_INFO_VALUE"} <= flags(r)
    text = explain(api, r, "savings")
    assert "kWh" not in text and "enough information" in text


def test_missing_winter_months_are_flagged_not_zero(api):
    r = analyse(api, "P1001332")
    assert flags(r) & {"LOW_COVERAGE_ANNUALISATION", "INSUFFICIENT_MONTHLY_DATA"}
    assert r["home"]["energy"]["gas_kwh"] is None or r["home"]["energy"]["gas_kwh"] > 0


def test_missing_gas_readings_use_flagged_typical_homes(api):
    r = analyse(api, "P1002021")
    assert "ENERGY_FROM_TYPICAL_HOMES" in flags(r)
    assert r["savings"]["status"] == "ok"  # estimated, and the estimate is flagged


# ---------- conflicting data ----------
def test_rating_and_usage_conflict_is_kept_and_flagged(api):
    r = analyse(api, "P90005")
    assert "CONFLICT_RATING_VS_USAGE" in flags(r)
    assert r["score"]["status"] == "ok"  # both inputs are kept, not discarded


def test_good_rating_with_very_high_usage_is_a_problem_area(api):
    r = analyse(api, "P1011233")
    assert "HIGH_INTENSITY" in {i["code"] for i in r["issues"]}


# ---------- infeasible retrofits ----------
def test_flat_with_dwelling_above_gets_no_loft_or_solar(api):
    r = analyse(api, "P1024619")
    for retrofit, reason in [("loft_insulation", "NO_LOFT_DWELLING_ABOVE"), ("solar_pv", "NO_SUITABLE_ROOF")]:
        x = rec(r, retrofit)
        assert x["feasibility"] == "infeasible" and reason in x["reasons"] and x["rank"] is None
    s = scenario(api, "P1024619", ["loft_insulation", "solar_pv"])
    assert {x["retrofit"] for x in s["rejected"]} == {"loft_insulation", "solar_pv"}
    assert s["savings"]["retrofits"] == []  # rejected items are never computed


def test_already_installed_is_not_recommended(api):
    r = analyse(api, "P1033772")  # heat pump home
    assert rec(r, "air_source_heat_pump")["reasons"] == ["ALREADY_INSTALLED"]


# ---------- interacting retrofits ----------
def test_incremental_savings_add_up_to_the_package(api):
    r = analyse(api, "P10001")
    inc = [x["incremental_saving"]["net_kwh"] for x in r["recommendations"] if x["incremental_saving"]]
    assert sum(inc) == pytest.approx(r["savings"]["saving"]["net_kwh"], abs=1)


def test_heat_pump_is_worth_less_after_insulation(api):
    hp = rec(analyse(api, "P10001"), "air_source_heat_pump")
    assert hp["incremental_saving"]["gas_kwh"] < hp["standalone_saving"]["gas_kwh"]


def test_heat_pump_without_insulation_is_capped_with_insulate_first(api):
    s = scenario(api, "P10001", ["air_source_heat_pump"])
    hp = rec(s, "air_source_heat_pump")
    assert hp["suitability"] == "low" and "INSULATE_FIRST" in hp["reasons"]


# ---------- electricity rises after a heating change ----------
def test_heat_pump_raises_electricity_and_cuts_gas(api):
    s = scenario(api, "P10001", ["air_source_heat_pump"])
    saving = s["savings"]["saving"]
    assert saving["electricity_kwh"] < 0 < saving["gas_kwh"]  # negative saving = increase
    assert "ELECTRICITY_RISES_GAS_FALLS" in rec(s, "air_source_heat_pump")["reasons"]
    assert s["carbon"]["electricity_kg"] < 0 < s["carbon"]["gas_kg"]
    text = explain(api, s, "savings").lower()
    assert "electricity use goes up" in text


# ---------- too little information for savings or value ----------
def test_off_gas_home_is_scored_but_savings_out_of_scope(api):
    r = analyse(api, "P90005")
    assert r["score"]["status"] == "ok"
    assert r["savings"]["status"] == "out_of_scope" and "OUT_OF_SCOPE_FUEL" in flags(r)
    assert "mains gas or electricity" in explain(api, r, "savings")


# ---------- large is not the same as inefficient ----------
def test_large_efficient_home_is_not_called_poor(api):
    r = analyse(api, "P1014307")
    assert r["home"]["home"]["floor_area_m2"] > 200
    assert r["is_poor"] is False and r["score"]["score_class"] in {"good", "highly_efficient", "moderate"}
