"""Issue detection and the poor flag (README P2.6).

Rules are applied in the README table order; a rule is skipped when its input is unknown (None). Output is
sorted by severity (high → medium → low), table order within a severity. Peer percentiles come from config.
"""

from __future__ import annotations

from typing import Any

from greenhome.config import get_config
from greenhome.contracts import CleanHome, Feasibility, Issue, ScoreClass, ScoreResult

# Issue codes (binding, README P2.6).
HIGH_INTENSITY = "HIGH_INTENSITY"
LOW_RATING = "LOW_RATING"
POOR_ROOF_INSULATION = "POOR_ROOF_INSULATION"
POOR_WALL_INSULATION = "POOR_WALL_INSULATION"
SINGLE_GLAZING = "SINGLE_GLAZING"
OLD_HEATING = "OLD_HEATING"
NO_RENEWABLES = "NO_RENEWABLES"
NO_SMART_CONTROLS = "NO_SMART_CONTROLS"

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_POOR_CLASSES = {ScoreClass.poor.value, ScoreClass.very_poor.value}
_ROOFS_WITH_INSULATION = {"pitched_loft", "flat_roof", "room_in_roof"}
_ENERGY_FIELDS = ("electricity_kwh", "gas_kwh")
_OLD_HEATING = {"gas_boiler_old", "electric_direct", "electric_storage", "other_fuel_boiler"}


def _evidence(clean: CleanHome, *fields: str) -> dict[str, Any]:
    """Input values of `fields` plus their provenance."""
    return {
        **{f: getattr(clean.home, f) for f in fields},
        "provenance": {f: clean.provenance.get(f) for f in fields},
    }


def _intensity_issue(clean: CleanHome) -> Issue | None:
    h, intensity = clean.home, clean.intensity_kwh_m2
    energy_imputed = any(clean.provenance.get(f) == "imputed" for f in _ENERGY_FIELDS)
    if energy_imputed or intensity is None or h.floor_area_m2 is None:
        return None
    peers = get_config().peers(h.property_type, h.floor_area_m2)
    if intensity > peers["p90"]:
        severity, above = "high", "90%"
    elif intensity > peers["p75"]:
        severity, above = "medium", "75%"
    else:
        return None
    return Issue(
        code=HIGH_INTENSITY,
        severity=severity,
        component="consumption_intensity",
        message=f"Energy use per m² is higher than {above} of similar homes.",
        evidence={
            "intensity_kwh_m2": intensity,
            "peer_p75": peers["p75"],
            "peer_p90": peers["p90"],
            "property_type": h.property_type,
            "floor_area_m2": h.floor_area_m2,
            "provenance": {f: clean.provenance.get(f) for f in (*_ENERGY_FIELDS, "floor_area_m2")},
        },
    )


def detect_issues(
    clean: CleanHome, score: ScoreResult, feasibility: dict[str, tuple[str, list[str]]]
) -> tuple[list[Issue], bool | None]:
    """(issues sorted by severity, is_poor). is_poor is None when the score is insufficient."""
    h = clean.home
    is_poor = score.score_class in _POOR_CLASSES if score.status == "ok" else None
    issues: list[Issue | None] = [_intensity_issue(clean)]

    def add(code: str, severity: str, component: str, message: str, *fields: str) -> None:
        issues.append(Issue(code=code, severity=severity, component=component, message=message,
                            evidence=_evidence(clean, *fields)))

    if h.energy_rating in {"F", "G"}:
        add(LOW_RATING, "high", "energy_efficiency", f"Energy rating {h.energy_rating} is very low.",
            "energy_rating")
    elif h.energy_rating == "E":
        add(LOW_RATING, "medium", "energy_efficiency", "Energy rating E is below average.", "energy_rating")
    if h.roof_type in _ROOFS_WITH_INSULATION and h.roof_insulation in {"none", "low"}:
        add(POOR_ROOF_INSULATION, "high" if h.roof_insulation == "none" else "medium", "insulation",
            f"Roof insulation is {h.roof_insulation}.", "roof_type", "roof_insulation")
    if h.wall_insulation == "none":
        add(POOR_WALL_INSULATION, "high", "insulation", "Walls are not insulated.",
            "wall_type", "wall_insulation")
    if h.glazing == "single":
        add(SINGLE_GLAZING, "high", "glazing", "Windows are single glazed.", "glazing")
    elif h.glazing == "partial_double":
        add(SINGLE_GLAZING, "medium", "glazing", "Some windows are still single glazed.", "glazing")
    if h.heating_system in _OLD_HEATING:
        add(OLD_HEATING, "high", "heating", "The heating system is old or inefficient.", "heating_system")
    if h.renewables == "none" and feasibility["solar_pv"][0] == Feasibility.feasible.value:
        add(NO_RENEWABLES, "medium", "renewables", "No renewables, and solar panels look feasible.",
            "renewables")
    if h.smart_controls in {"none", "timer_only"}:
        add(NO_SMART_CONTROLS, "low", "smart_controls", "Heating controls are basic.", "smart_controls")

    found = sorted((i for i in issues if i is not None), key=lambda i: _SEVERITY_ORDER[i.severity])
    return found, is_poor
