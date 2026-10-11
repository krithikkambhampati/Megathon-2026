from __future__ import annotations

from pathlib import Path

import pytest

from greenhome.contracts import AnalysisResult, RejectedRetrofit, Scenario
from greenhome.format import fmt_intensity
from greenhome.llm.facts import build_fact_sheet, build_facts, data_notes, humanise

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
IDS = ["P10001", "P90002", "P90003", "P90004", "P90005"]
SECTIONS = ["score", "recommendations", "savings", "value"]


def _result(fx: str) -> AnalysisResult:
    return AnalysisResult.model_validate_json((FIXTURES / f"analysis_result_{fx}.json").read_text())


@pytest.fixture(scope="module")
def results() -> dict[str, AnalysisResult]:
    return {fx: _result(fx) for fx in IDS}


@pytest.mark.parametrize("fx", IDS)
@pytest.mark.parametrize("section", SECTIONS)
def test_every_sheet_builds_and_stays_small(results, fx, section) -> None:
    sheet = build_fact_sheet(results[fx], section)
    assert [f.id for f in sheet.facts] == [f"F{i + 1}" for i in range(len(sheet.facts))]
    assert len(sheet.lines()) <= 6000  # ≈ 1.5k tokens (BUILD_GUIDE P4 hazard 5)
    for f in sheet.facts:
        assert f.display and f.display != "—" and f.label


def test_prompt_lines_never_show_raw_values(results) -> None:
    r = results["P10001"]
    lines = build_fact_sheet(r, "recommendations").lines()
    assert "1243.5424" not in lines and "-3600" not in lines
    assert (
        "Air source heat pump on its own · estimated saving · electricity: 3,600 kWh/year increase" in lines
    )


def test_negative_saving_reads_increase_and_points_up(results) -> None:
    sheet = build_fact_sheet(results["P10001"], "savings")
    elec = sheet.get("savings.saving.electricity_kwh")
    assert elec.display == "1,240 kWh/year increase" and elec.direction == "up"
    assert sheet.get("savings.saving.gas_kwh").direction == "down"
    assert sheet.view["savings"]["saving"]["electricity_kwh_increase"] is True


def test_display_strings_come_from_format(results) -> None:
    r = results["P10001"]
    value = build_fact_sheet(r, "value")
    assert value.get("value.current_value_gbp").display == "£350,000"
    assert value.get("value.uplift_pct_range").display == "2.5% – 3.5%"
    assert value.get("value.rating_change").display == "E → C"
    score = build_fact_sheet(r, "score")
    assert score.get("score.score").display == "32" and score.get("score.score_class").display == "Poor"
    assert score.get("score.components.energy_efficiency.weight").display == "25.0%"
    assert "Poor from 30" in score.get("score.class_bands").display


@pytest.mark.parametrize("fx,section", [("P90003", "score"), ("P90003", "savings"), ("P90005", "savings")])
def test_insufficient_or_out_of_scope_sections_have_no_numbers(results, fx, section) -> None:
    sheet = build_fact_sheet(results[fx], section)
    assert sheet.statuses[section] in ("insufficient", "out_of_scope")
    assert not [f for f in sheet.facts if f.unit != "text"]


def test_recommendations_standalone_only_unless_focus(results) -> None:
    r = results["P10001"]
    plain = build_fact_sheet(r, "recommendations")
    assert not [f for f in plain.facts if "incremental" in f.key]
    infeasible = plain.view["recommendations"]["infeasible"]
    assert [(i["name"], i["reason_codes"]) for i in infeasible] == [
        ("Solid wall insulation", ["WRONG_WALL_TYPE"])
    ]
    assert plain.get("recommendations.solid_wall_insulation.cost_gbp") is None
    assert "WRONG_WALL_TYPE" in plain.reasons
    focus = build_fact_sheet(r, "recommendations", focus=["air_source_heat_pump", "solid_wall_insulation"])
    assert focus.get("recommendations.air_source_heat_pump.incremental_saving.electricity_kwh") is not None
    assert focus.get("recommendations.solid_wall_insulation.cost_gbp") is not None


def test_zero_fuel_rows_are_dropped(results) -> None:
    sheet = build_fact_sheet(results["P10001"], "recommendations")
    assert sheet.get("recommendations.loft_insulation.standalone_saving.electricity_kwh") is None
    assert sheet.get("recommendations.loft_insulation.standalone_saving.gas_kwh") is not None


def test_whatif_sheet_has_diff_package_reasons_and_rejected(results) -> None:
    base = results["P10001"]
    new = base.model_copy(deep=True)
    new.scenario = Scenario(
        name="only solar_pv", mode="custom", retrofits=["solar_pv", "solid_wall_insulation"]
    )
    new.savings.retrofits = ["solar_pv"]
    new.rejected = [RejectedRetrofit(retrofit="solid_wall_insulation", reason="WRONG_WALL_TYPE")]
    new.score_after.score = 40
    new = AnalysisResult.model_validate(new.model_dump())
    sheet = build_fact_sheet(new, "whatif", base=base)
    assert sheet.get("diff.score_after.base").display == "89"
    assert sheet.get("diff.score_after.new").display == "40"
    assert sheet.get("diff.score_after.delta").display == "−49"
    assert sheet.get("diff.improvement_potential_pct.base") is None  # retrofit-only what-if
    assert sheet.get("rejected.solid_wall_insulation") is not None and "WRONG_WALL_TYPE" in sheet.reasons
    assert [i["retrofit"] for i in sheet.view["recommendations"]["items"]] == ["solar_pv"]
    assert sheet.view["diff"]["removed"]


def test_whatif_needs_base(results) -> None:
    with pytest.raises(ValueError):
        build_fact_sheet(results["P10001"], "whatif")


def test_notes_dedupe_group_and_have_no_counts_or_raw_values(results) -> None:
    r = results["P90003"]
    notes = data_notes(r.flags + r.home.flags)
    assert len(notes) == len(set(notes))
    grouped = [n for n in notes if "answers not given" in n]
    assert len(grouped) == 1 and "floor area" in grouped[0]
    assert not any("70.0" in n or "estimated as" in n for n in notes)


def test_humanise_replaces_enum_values() -> None:
    assert humanise("Gas use does not match gas_boiler_condensing heating.") == (
        "Gas use does not match modern gas boiler (condensing) heating."
    )


def test_build_facts_covers_all_sections_with_unique_ids(results) -> None:
    facts = build_facts(results["P10001"])
    assert len({f.id for f in facts}) == len(facts)
    keys = {f.key.split(".")[0] for f in facts}
    assert {"score", "recommendations", "savings", "carbon", "value"} <= keys


def test_score_sheet_has_floor_area_and_peer_use_with_shared_formatters(results) -> None:
    sheet = build_fact_sheet(results["P10001"], "score")
    assert sheet.get("home.floor_area_m2").display == "85 m²"
    assert sheet.get("peer.intensity_kwh_m2").display == "198 kWh/m²/year"
    # the typical-home figure comes from P1's peer table, so read it from the result rather than hard-code it
    assert sheet.get("peer.p50_kwh_m2").display == fmt_intensity(results["P10001"].peer.p50_kwh_m2)


def test_notes_use_field_labels(results) -> None:
    notes = data_notes(results["P90002"].flags)
    assert any("loft insulation, outdoor space for a heat pump" in n for n in notes)


def test_custom_scenario_is_not_called_the_recommended_plan() -> None:
    """A what-if result (e.g. solar only) must not be explained as "all the recommended retrofits"."""
    from greenhome.contracts import HomeInput
    from greenhome.core.orchestrator import Engine
    from greenhome.llm.explainer import explain

    home = HomeInput.model_validate_json(
        (Path(__file__).resolve().parents[2] / "fixtures" / "home_input_P10001.json").read_text()
    )
    engine = Engine.from_config()
    custom = engine.run_scenario(home, Scenario(name="custom", mode="custom", retrofits=["solar_pv"]))
    for section in ("savings", "score"):
        text, _ = explain(custom, section, None)
        assert "all the recommended retrofits" not in text, section
    assert "retrofits in this scenario" in explain(custom, "savings", None)[0]
    plan_text, _ = explain(engine.analyse(home), "savings", None)
    assert "all the recommended retrofits" in plan_text


def test_no_score_after_when_todays_score_is_insufficient() -> None:
    """Eval item S68: for a home we can't score, neither the LLM nor the template may promise a score."""
    from greenhome.contracts import HomeInput
    from greenhome.core.orchestrator import Engine
    from greenhome.llm.explainer import explain

    home = HomeInput.model_validate_json(
        (Path(__file__).resolve().parents[2] / "fixtures" / "home_input_P90003.json").read_text()
    )
    result = Engine.from_config().analyse(home)
    assert result.score.status == "insufficient"
    sheet = build_fact_sheet(result, "score")
    assert sheet.get("score_after.score") is None
    text, _ = explain(result, "score", None)
    assert "estimated score would be" not in text  # the template's score-after sentence
