"""Issue rules and the poor flag (README P2.6)."""

from __future__ import annotations

import pytest
from conftest import home_input, make_clean

from greenhome.config import get_config
from greenhome.contracts import ScoreResult
from greenhome.core.feasibility import feasible_set
from greenhome.core.issues import detect_issues


def score(score_class: str | None = "poor", status: str = "ok") -> ScoreResult:
    ok = status == "ok"
    return ScoreResult(status=status, score=36 if ok else None, score_raw=36.0 if ok else None,
                       score_class=score_class if ok else None, score_range=None, components=[],
                       method_version="score-v1")


def typical(**overrides):
    """make_clean with intensity at the peer median, so only the rule under test can fire."""
    clean = make_clean(home_input(**overrides))
    p50 = get_config().peers(clean.home.property_type, clean.home.floor_area_m2)["p50"]
    return clean.model_copy(update={"intensity_kwh_m2": p50})


def issues_for(clean=None, feasibility=None, **overrides):
    clean = clean or typical(**overrides)
    issues, _ = detect_issues(clean, score(), feasibility or feasible_set(clean.home))
    return {i.code: i for i in issues}


def with_intensity(intensity: float):
    return make_clean().model_copy(update={"intensity_kwh_m2": intensity})


def test_p10001_issues():
    issues, is_poor = detect_issues(typical(), score(), feasible_set(home_input()))
    assert is_poor is True
    assert [(i.code, i.severity) for i in issues] == [
        ("POOR_WALL_INSULATION", "high"),
        ("SINGLE_GLAZING", "high"),
        ("LOW_RATING", "medium"),
        ("POOR_ROOF_INSULATION", "medium"),
        ("NO_RENEWABLES", "medium"),
    ]


def test_high_intensity_severity_from_peers():
    peers = get_config().peers("semi_detached", 85.0)
    high = issues_for(with_intensity(peers["p90"] + 1))["HIGH_INTENSITY"]
    assert (high.severity, high.component) == ("high", "consumption_intensity")
    assert high.evidence["peer_p90"] == peers["p90"]
    assert high.evidence["provenance"]["gas_kwh"] == "user"
    assert issues_for(with_intensity(peers["p75"] + 1))["HIGH_INTENSITY"].severity == "medium"
    assert "HIGH_INTENSITY" not in issues_for(with_intensity(peers["p75"]))
    assert "HIGH_INTENSITY" not in issues_for(with_intensity(None))


def test_high_intensity_skipped_for_imputed_energy():
    clean = with_intensity(get_config().peers("semi_detached", 85.0)["p90"] + 1)
    clean = clean.model_copy(update={"provenance": {**clean.provenance, "gas_kwh": "imputed"}})
    assert "HIGH_INTENSITY" not in issues_for(clean)


@pytest.mark.parametrize(("rating", "severity"), [("E", "medium"), ("F", "high"), ("G", "high"),
                                                  ("D", None), (None, None)])
def test_low_rating(rating, severity):
    issue = issues_for(energy_rating=rating).get("LOW_RATING")
    assert (issue.severity if issue else None) == severity
    if issue:
        assert issue.component == "energy_efficiency"
        assert issue.evidence == {"energy_rating": rating, "provenance": {"energy_rating": "user"}}


@pytest.mark.parametrize(("roof_type", "insulation", "severity"), [
    ("pitched_loft", "none", "high"), ("flat_roof", "low", "medium"), ("room_in_roof", "none", "high"),
    ("dwelling_above", "none", None), ("pitched_loft", "medium", None), (None, "none", None),
    ("pitched_loft", None, None),
])
def test_poor_roof_insulation(roof_type, insulation, severity):
    issue = issues_for(roof_type=roof_type, roof_insulation=insulation).get("POOR_ROOF_INSULATION")
    assert (issue.severity if issue else None) == severity
    if issue:
        assert issue.component == "insulation"


@pytest.mark.parametrize(("insulation", "severity"), [("none", "high"), ("partial", None), (None, None)])
def test_poor_wall_insulation(insulation, severity):
    issue = issues_for(wall_insulation=insulation).get("POOR_WALL_INSULATION")
    assert (issue.severity if issue else None) == severity


@pytest.mark.parametrize(("glazing", "severity"), [("single", "high"), ("partial_double", "medium"),
                                                   ("secondary", None), ("double", None), (None, None)])
def test_single_glazing(glazing, severity):
    issue = issues_for(glazing=glazing).get("SINGLE_GLAZING")
    assert (issue.severity if issue else None) == severity


@pytest.mark.parametrize(("heating", "severity"), [
    ("gas_boiler_old", "high"), ("electric_direct", "high"), ("electric_storage", "high"),
    ("other_fuel_boiler", "high"), ("gas_boiler_condensing", None), ("heat_pump", None), (None, None),
])
def test_old_heating(heating, severity):
    issue = issues_for(heating_system=heating).get("OLD_HEATING")
    assert (issue.severity if issue else None) == severity
    if issue:
        assert issue.component == "heating"


def test_no_renewables_depends_on_feasibility():
    assert issues_for()["NO_RENEWABLES"].severity == "medium"
    assert "NO_RENEWABLES" not in issues_for(property_type="flat")  # solar infeasible
    assert "NO_RENEWABLES" not in issues_for(listed_or_conservation="yes")  # solar needs survey
    assert "NO_RENEWABLES" not in issues_for(renewables="solar_thermal")
    survey = {**feasible_set(home_input()), "solar_pv": ("needs_survey", ["UNKNOWN_INPUT_SURVEY"])}
    assert "NO_RENEWABLES" not in issues_for(feasibility=survey)


@pytest.mark.parametrize(("smart", "severity"), [("none", "low"), ("timer_only", "low"),
                                                 ("programmer_thermostat", None), (None, None)])
def test_no_smart_controls(smart, severity):
    issue = issues_for(smart_controls=smart).get("NO_SMART_CONTROLS")
    assert (issue.severity if issue else None) == severity


@pytest.mark.parametrize(("score_class", "status", "is_poor"), [
    ("very_poor", "ok", True), ("poor", "ok", True), ("moderate", "ok", False),
    ("highly_efficient", "ok", False), (None, "insufficient", None),
])
def test_is_poor(score_class, status, is_poor):
    _, got = detect_issues(make_clean(), score(score_class, status), feasible_set(home_input()))
    assert got is is_poor


def test_sorted_by_severity_then_table_order():
    clean = typical(energy_rating="G", smart_controls="none", heating_system="gas_boiler_old",
                    glazing="partial_double")
    issues, _ = detect_issues(clean, score(), feasible_set(clean.home))
    assert [(i.code, i.severity) for i in issues] == [
        ("LOW_RATING", "high"),
        ("POOR_WALL_INSULATION", "high"),
        ("OLD_HEATING", "high"),
        ("POOR_ROOF_INSULATION", "medium"),
        ("SINGLE_GLAZING", "medium"),
        ("NO_RENEWABLES", "medium"),
        ("NO_SMART_CONTROLS", "low"),
    ]
