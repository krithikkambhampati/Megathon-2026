from __future__ import annotations

import json
from pathlib import Path

import pytest

from greenhome.contracts import AnalysisResult, HomeInput, Scenario
from greenhome.core.orchestrator import Engine
from greenhome.llm.budget import Deadline
from greenhome.llm.fake import ScriptedClient
from greenhome.llm.settings import load_llm_settings
from greenhome.llm.whatif_parser import parse_whatif

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures"
GOLD = [
    json.loads(line) for line in (ROOT / "evaluation" / "whatif_parse_gold.jsonl").read_text().splitlines()
]
SETTINGS = load_llm_settings(env={})


def _home(fx: str) -> HomeInput:
    return HomeInput.model_validate_json((FIXTURES / f"home_input_{fx}.json").read_text())


def _base(fx: str) -> AnalysisResult:
    return AnalysisResult.model_validate_json((FIXTURES / f"analysis_result_{fx}.json").read_text())


def _norm(sc: Scenario | dict | None):
    if sc is None:
        return None
    d = sc.model_dump() if isinstance(sc, Scenario) else sc
    return d["mode"], list(d["retrofits"]) if d["mode"] == "custom" else [], d["overrides"]


def test_gold_set_shape() -> None:
    assert len(GOLD) == 50 and len({g["id"] for g in GOLD}) == 50
    for g in GOLD:
        if g["expected"] is not None:
            Scenario.model_validate({"name": "x", **g["expected"]})


@pytest.mark.parametrize("item", [g for g in GOLD if g["rules_should_parse"]], ids=lambda g: g["id"])
def test_rules_parse_the_gold_items(item) -> None:
    current = Scenario.model_validate(item["current_scenario"]) if item["current_scenario"] else None
    res = parse_whatif(item["message"], _home(item["home"]), _base(item["home"]), current)
    assert _norm(res.scenario) == _norm(item["expected"]), res.clarify
    if item["expected"] is None:
        assert res.clarify


@pytest.mark.parametrize("item", [g for g in GOLD if not g["rules_should_parse"]], ids=lambda g: g["id"])
def test_rules_do_not_guess_on_llm_items(item) -> None:
    current = Scenario.model_validate(item["current_scenario"]) if item["current_scenario"] else None
    res = parse_whatif(item["message"], _home(item["home"]), _base(item["home"]), current)
    assert res.scenario is None and res.clarify  # rules don't misparse; the LLM fallback gets a chance


def test_demo_turn_two_caps_the_heat_pump_with_insulate_first() -> None:
    engine = Engine.from_config()
    home = _home("P10001")
    base = engine.analyse(home)
    t1 = parse_whatif("What if I only install solar?", home, base).scenario
    t2 = parse_whatif("and a heat pump but no loft insulation?", home, base, t1).scenario
    assert t2.retrofits == ["solar_pv", "air_source_heat_pump"]
    hp = next(
        r for r in engine.run_scenario(home, t2).recommendations if r.retrofit == "air_source_heat_pump"
    )
    assert hp.suitability == "low" and "INSULATE_FIRST" in hp.reasons


def test_gas_override_keeps_the_other_fuels_monthly_readings() -> None:
    engine = Engine.from_config()
    home = _home("P90004")  # 12 monthly readings, gas missing for 3 winter months
    res = parse_whatif("what if my gas use was 9,000 kWh?", home, engine.analyse(home))
    energy = res.scenario.overrides["energy"]
    assert energy["annual_gas_kwh"] == 9000 and all(m["gas_kwh"] is None for m in energy["monthly"])
    assert any(m["electricity_kwh"] for m in energy["monthly"])
    after = engine.run_scenario(home, res.scenario)
    assert after.home.energy.gas_kwh == 9000 and after.home.energy.electricity_kwh == 3600
    assert "ENERGY_FROM_TYPICAL_HOMES" not in [f.code for f in after.flags]
    assert [(f.key, f.display) for f in res.user_facts] == [("user.annual_gas_kwh", "9,000 kWh/year")]


def test_invalid_override_is_never_returned() -> None:
    res = parse_whatif("what if my gas use was -5 kWh", _home("P10001"), _base("P10001"))
    assert res.scenario is None or res.scenario.overrides.get("energy", {}).get("annual_gas_kwh", 0) >= 0


def test_llm_fallback_is_validated() -> None:
    home, base = _home("P10001"), _base("P10001")
    llm = ScriptedClient(['{"mode": "custom", "retrofits": ["air_source_heat_pump"]}'])
    res = parse_whatif(
        "let's go fully electric", home, base, llm=llm, deadline=Deadline(25), settings=SETTINGS
    )
    assert res.method == "llm" and res.scenario.retrofits == ["air_source_heat_pump"]
    assert llm.calls[0].json_schema["properties"]["retrofits"]["items"]["enum"][0] == "loft_insulation"
    assert llm.calls[0].timeout_s <= SETTINGS.cap("whatif_parse")


@pytest.mark.parametrize("reply", ['{"mode": "custom", "retrofits": ["teleporter"]}', "{", '{"mode": "x"}'])
def test_bad_llm_json_asks_to_clarify(reply) -> None:
    res = parse_whatif(
        "let's go fully electric",
        _home("P10001"),
        _base("P10001"),
        llm=ScriptedClient([reply]),
        deadline=Deadline(25),
        settings=SETTINGS,
    )
    assert res.scenario is None and res.clarify
