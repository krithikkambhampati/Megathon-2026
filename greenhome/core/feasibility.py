"""Deterministic retrofit feasibility with reason codes (BUILD_GUIDE P2.7). P1's simulator imports it too.

Each retrofit has an ordered rule list. The first matching `infeasible` rule wins (single reason); otherwise
every matching `needs_survey` rule contributes its reason; otherwise the retrofit is feasible. `info` rules
append a reason without changing the verdict (heat pump on other fuels: allowed, savings out of scope).
The value sets below are §7.2 vocabulary, not tunable thresholds.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from greenhome.contracts import FEATURE_FIELDS, Feasibility, HomeInput, Retrofit

# Reason codes (binding for P4 templates, BUILD_GUIDE P2.7).
ALREADY_INSTALLED = "ALREADY_INSTALLED"
NO_LOFT_DWELLING_ABOVE = "NO_LOFT_DWELLING_ABOVE"
FLAT_ROOF_INSULATION_DIFFERENT_MEASURE = "FLAT_ROOF_INSULATION_DIFFERENT_MEASURE"
WRONG_WALL_TYPE = "WRONG_WALL_TYPE"
LISTED_OR_CONSERVATION = "LISTED_OR_CONSERVATION"
NO_SUITABLE_ROOF = "NO_SUITABLE_ROOF"
NEEDS_OUTDOOR_SPACE_CHECK = "NEEDS_OUTDOOR_SPACE_CHECK"
UNKNOWN_INPUT_SURVEY = "UNKNOWN_INPUT_SURVEY"
OUT_OF_SCOPE_FUEL = "OUT_OF_SCOPE_FUEL"
INCOMPATIBLE_HEATING = "INCOMPATIBLE_HEATING"

_INF, _SURVEY, _OK = Feasibility.infeasible.value, Feasibility.needs_survey.value, Feasibility.feasible.value
_INFO = "info"
_FLATS = {"flat", "maisonette"}

Rule = tuple[str, str, Callable[[dict[str, Any]], bool]]


def _unknown(*fields: str) -> Callable[[dict[str, Any]], bool]:
    return lambda h: any(h[f] is None for f in fields)


def _wrong_wall(wall: str) -> Callable[[dict[str, Any]], bool]:
    return lambda h: h["wall_type"] is not None and h["wall_type"] != wall


_RULES: dict[str, list[Rule]] = {
    "loft_insulation": [
        (_INF, NO_LOFT_DWELLING_ABOVE, lambda h: h["roof_type"] == "dwelling_above"),
        (_INF, FLAT_ROOF_INSULATION_DIFFERENT_MEASURE, lambda h: h["roof_type"] == "flat_roof"),
        (_INF, ALREADY_INSTALLED, lambda h: h["roof_insulation"] == "full"),
        (_SURVEY, UNKNOWN_INPUT_SURVEY, _unknown("roof_type", "roof_insulation")),
    ],
    "cavity_wall_insulation": [
        (_INF, WRONG_WALL_TYPE, _wrong_wall("cavity")),
        (_INF, ALREADY_INSTALLED, lambda h: h["wall_insulation"] == "full"),
        (_SURVEY, UNKNOWN_INPUT_SURVEY, _unknown("wall_type", "wall_insulation")),
    ],
    "solid_wall_insulation": [
        (_INF, WRONG_WALL_TYPE, _wrong_wall("solid")),
        (_INF, ALREADY_INSTALLED, lambda h: h["wall_insulation"] == "full"),
        (_SURVEY, UNKNOWN_INPUT_SURVEY, _unknown("wall_type", "wall_insulation")),
        (_SURVEY, LISTED_OR_CONSERVATION, lambda h: h["listed_or_conservation"] == "yes"),  # internal only
    ],
    "double_glazing": [
        (_INF, ALREADY_INSTALLED, lambda h: h["glazing"] in {"double", "triple"}),
        # The message layer suggests secondary glazing for this reason.
        (_INF, LISTED_OR_CONSERVATION, lambda h: h["listed_or_conservation"] == "yes"),
        (_SURVEY, UNKNOWN_INPUT_SURVEY, _unknown("glazing")),
    ],
    "air_source_heat_pump": [
        (_INF, ALREADY_INSTALLED, lambda h: h["heating_system"] == "heat_pump"),
        (_SURVEY, UNKNOWN_INPUT_SURVEY, _unknown("heating_system")),
        (_SURVEY, NEEDS_OUTDOOR_SPACE_CHECK,
         lambda h: h["property_type"] in _FLATS or h["outdoor_space"] != "yes"),
        (_INFO, OUT_OF_SCOPE_FUEL, lambda h: h["main_fuel"] == "other"),
    ],
    "solar_pv": [
        (_INF, ALREADY_INSTALLED, lambda h: h["renewables"] in {"solar_pv", "solar_pv_battery"}),
        (_INF, NO_SUITABLE_ROOF,
         lambda h: h["roof_type"] == "dwelling_above" or h["property_type"] in _FLATS),
        (_SURVEY, LISTED_OR_CONSERVATION, lambda h: h["listed_or_conservation"] == "yes"),
        (_SURVEY, UNKNOWN_INPUT_SURVEY, _unknown("roof_type", "property_type")),
    ],
    "smart_thermostat": [
        (_INF, ALREADY_INSTALLED, lambda h: h["smart_controls"] in {"smart_thermostat", "smart_zoned"}),
        (_INF, INCOMPATIBLE_HEATING, lambda h: h["heating_system"] == "electric_direct"),
        (_SURVEY, UNKNOWN_INPUT_SURVEY, _unknown("heating_system", "smart_controls")),
    ],
}


def _evaluate(rules: list[Rule], h: dict[str, Any]) -> tuple[str, list[str]]:
    fired = [(verdict, reason) for verdict, reason, test in rules if test(h)]
    info = [r for v, r in fired if v == _INFO]
    infeasible = [r for v, r in fired if v == _INF]
    if infeasible:
        return _INF, infeasible[:1] + info
    survey = list(dict.fromkeys(r for v, r in fired if v == _SURVEY))
    return (_SURVEY if survey else _OK), survey + info


def feasible_set(home: HomeInput, unknown: Iterable[str] = ()) -> dict[str, tuple[str, list[str]]]:
    """All 7 retrofits in catalogue order → (feasibility, reason codes). Fields in `unknown` count as None."""
    unknown = set(unknown)
    h = {f: None if f in unknown else getattr(home, f) for f in FEATURE_FIELDS}
    return {r.value: _evaluate(_RULES[r.value], h) for r in Retrofit}
