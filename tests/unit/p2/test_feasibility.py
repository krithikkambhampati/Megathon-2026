"""Feasibility rules (README P2.7)."""

from __future__ import annotations

import pytest
from conftest import home_input

from greenhome.contracts import Retrofit
from greenhome.core.feasibility import (
    ALREADY_INSTALLED,
    FLAT_ROOF_INSULATION_DIFFERENT_MEASURE,
    INCOMPATIBLE_HEATING,
    LISTED_OR_CONSERVATION,
    NEEDS_OUTDOOR_SPACE_CHECK,
    NO_LOFT_DWELLING_ABOVE,
    NO_SUITABLE_ROOF,
    OUT_OF_SCOPE_FUEL,
    UNKNOWN_INPUT_SURVEY,
    WRONG_WALL_TYPE,
    feasible_set,
)

INF, SURVEY, OK = "infeasible", "needs_survey", "feasible"

CASES = [
    # loft_insulation
    ("loft_insulation", {"roof_type": "dwelling_above"}, INF, [NO_LOFT_DWELLING_ABOVE]),
    ("loft_insulation", {"roof_type": "flat_roof"}, INF, [FLAT_ROOF_INSULATION_DIFFERENT_MEASURE]),
    ("loft_insulation", {"roof_insulation": "full"}, INF, [ALREADY_INSTALLED]),
    ("loft_insulation", {"roof_type": None}, SURVEY, [UNKNOWN_INPUT_SURVEY]),
    ("loft_insulation", {"roof_insulation": None}, SURVEY, [UNKNOWN_INPUT_SURVEY]),
    ("loft_insulation", {"roof_type": None, "roof_insulation": None}, SURVEY, [UNKNOWN_INPUT_SURVEY]),
    ("loft_insulation", {"roof_type": "room_in_roof"}, OK, []),
    ("loft_insulation", {"roof_insulation": "medium"}, OK, []),
    # cavity_wall_insulation
    ("cavity_wall_insulation", {"wall_type": "solid"}, INF, [WRONG_WALL_TYPE]),
    ("cavity_wall_insulation", {"wall_type": "timber_or_system"}, INF, [WRONG_WALL_TYPE]),
    ("cavity_wall_insulation", {"wall_insulation": "full"}, INF, [ALREADY_INSTALLED]),
    ("cavity_wall_insulation", {"wall_type": None}, SURVEY, [UNKNOWN_INPUT_SURVEY]),
    ("cavity_wall_insulation", {"wall_insulation": None}, SURVEY, [UNKNOWN_INPUT_SURVEY]),
    ("cavity_wall_insulation", {"wall_insulation": "partial"}, OK, []),
    # solid_wall_insulation
    ("solid_wall_insulation", {}, INF, [WRONG_WALL_TYPE]),
    ("solid_wall_insulation", {"wall_type": "solid"}, OK, []),
    ("solid_wall_insulation", {"wall_type": "solid", "wall_insulation": "full"}, INF, [ALREADY_INSTALLED]),
    ("solid_wall_insulation", {"wall_type": "solid", "wall_insulation": None}, SURVEY,
     [UNKNOWN_INPUT_SURVEY]),
    ("solid_wall_insulation", {"wall_type": "solid", "listed_or_conservation": "yes"}, SURVEY,
     [LISTED_OR_CONSERVATION]),
    ("solid_wall_insulation", {"wall_type": None, "listed_or_conservation": "yes"}, SURVEY,
     [UNKNOWN_INPUT_SURVEY, LISTED_OR_CONSERVATION]),
    # double_glazing
    ("double_glazing", {"glazing": "double"}, INF, [ALREADY_INSTALLED]),
    ("double_glazing", {"glazing": "triple"}, INF, [ALREADY_INSTALLED]),
    ("double_glazing", {"listed_or_conservation": "yes"}, INF, [LISTED_OR_CONSERVATION]),
    ("double_glazing", {"glazing": "double", "listed_or_conservation": "yes"}, INF, [ALREADY_INSTALLED]),
    ("double_glazing", {"glazing": None}, SURVEY, [UNKNOWN_INPUT_SURVEY]),
    ("double_glazing", {"glazing": "secondary"}, OK, []),
    ("double_glazing", {"glazing": "partial_double", "listed_or_conservation": None}, OK, []),
    # air_source_heat_pump
    ("air_source_heat_pump", {"heating_system": "heat_pump"}, INF, [ALREADY_INSTALLED]),
    ("air_source_heat_pump", {"heating_system": None}, SURVEY, [UNKNOWN_INPUT_SURVEY]),
    ("air_source_heat_pump", {"outdoor_space": "no"}, SURVEY, [NEEDS_OUTDOOR_SPACE_CHECK]),
    ("air_source_heat_pump", {"outdoor_space": None}, SURVEY, [NEEDS_OUTDOOR_SPACE_CHECK]),
    ("air_source_heat_pump", {"property_type": "flat"}, SURVEY, [NEEDS_OUTDOOR_SPACE_CHECK]),
    ("air_source_heat_pump", {"property_type": "maisonette"}, SURVEY, [NEEDS_OUTDOOR_SPACE_CHECK]),
    ("air_source_heat_pump", {"heating_system": None, "outdoor_space": "no"}, SURVEY,
     [UNKNOWN_INPUT_SURVEY, NEEDS_OUTDOOR_SPACE_CHECK]),
    ("air_source_heat_pump", {"main_fuel": "other", "heating_system": "other_fuel_boiler"}, OK,
     [OUT_OF_SCOPE_FUEL]),
    ("air_source_heat_pump", {"main_fuel": "other", "outdoor_space": "no"}, SURVEY,
     [NEEDS_OUTDOOR_SPACE_CHECK, OUT_OF_SCOPE_FUEL]),
    ("air_source_heat_pump", {"main_fuel": "other", "heating_system": "heat_pump"}, INF,
     [ALREADY_INSTALLED, OUT_OF_SCOPE_FUEL]),
    ("air_source_heat_pump", {"main_fuel": None}, OK, []),
    # solar_pv
    ("solar_pv", {"renewables": "solar_pv"}, INF, [ALREADY_INSTALLED]),
    ("solar_pv", {"renewables": "solar_pv_battery"}, INF, [ALREADY_INSTALLED]),
    ("solar_pv", {"renewables": "solar_thermal"}, OK, []),
    ("solar_pv", {"roof_type": "dwelling_above"}, INF, [NO_SUITABLE_ROOF]),
    ("solar_pv", {"property_type": "flat"}, INF, [NO_SUITABLE_ROOF]),
    ("solar_pv", {"property_type": "maisonette"}, INF, [NO_SUITABLE_ROOF]),
    ("solar_pv", {"listed_or_conservation": "yes"}, SURVEY, [LISTED_OR_CONSERVATION]),
    ("solar_pv", {"roof_type": None}, SURVEY, [UNKNOWN_INPUT_SURVEY]),
    ("solar_pv", {"property_type": None}, SURVEY, [UNKNOWN_INPUT_SURVEY]),
    ("solar_pv", {"roof_type": None, "listed_or_conservation": "yes"}, SURVEY,
     [LISTED_OR_CONSERVATION, UNKNOWN_INPUT_SURVEY]),
    ("solar_pv", {"roof_type": "flat_roof"}, OK, []),
    # smart_thermostat
    ("smart_thermostat", {"smart_controls": "smart_thermostat"}, INF, [ALREADY_INSTALLED]),
    ("smart_thermostat", {"smart_controls": "smart_zoned"}, INF, [ALREADY_INSTALLED]),
    ("smart_thermostat", {"heating_system": "electric_direct"}, INF, [INCOMPATIBLE_HEATING]),
    ("smart_thermostat", {"heating_system": None}, SURVEY, [UNKNOWN_INPUT_SURVEY]),
    ("smart_thermostat", {"smart_controls": None}, SURVEY, [UNKNOWN_INPUT_SURVEY]),
    ("smart_thermostat", {"heating_system": "electric_storage", "smart_controls": "none"}, OK, []),
]


@pytest.mark.parametrize(("retrofit", "overrides", "feasibility", "reasons"), CASES)
def test_rule(retrofit, overrides, feasibility, reasons):
    assert feasible_set(home_input(**overrides))[retrofit] == (feasibility, reasons)


def test_p10001():
    fs = feasible_set(home_input())
    assert fs["solid_wall_insulation"] == (INF, [WRONG_WALL_TYPE])
    assert {r: v for r, v in fs.items() if r != "solid_wall_insulation"} == {
        r: (OK, []) for r in ("loft_insulation", "cavity_wall_insulation", "double_glazing",
                              "air_source_heat_pump", "solar_pv", "smart_thermostat")
    }


def test_unknown_param_overrides_known_value():
    home = home_input(glazing="double", heating_system="heat_pump")
    assert feasible_set(home)["double_glazing"] == (INF, [ALREADY_INSTALLED])
    fs = feasible_set(home, unknown=["glazing", "heating_system"])
    assert fs["double_glazing"] == (SURVEY, [UNKNOWN_INPUT_SURVEY])
    assert fs["air_source_heat_pump"] == (SURVEY, [UNKNOWN_INPUT_SURVEY])
    assert fs["smart_thermostat"] == (SURVEY, [UNKNOWN_INPUT_SURVEY])
    assert home.glazing == "double"  # input not mutated


def test_flat_with_dwelling_above():
    fs = feasible_set(home_input(property_type="flat", roof_type="dwelling_above"))
    assert fs["loft_insulation"] == (INF, [NO_LOFT_DWELLING_ABOVE])
    assert fs["solar_pv"] == (INF, [NO_SUITABLE_ROOF])


def test_all_keys_in_catalogue_order():
    assert list(feasible_set(home_input())) == [r.value for r in Retrofit]
    assert list(feasible_set(home_input(), unknown=["roof_type"])) == [r.value for r in Retrofit]


def test_all_unknown_home_never_feasible_without_survey():
    fields = ("property_type", "roof_type", "roof_insulation", "wall_type", "wall_insulation", "glazing",
              "heating_system", "main_fuel", "renewables", "smart_controls", "listed_or_conservation",
              "outdoor_space")
    fs = feasible_set(home_input(**dict.fromkeys(fields)))
    assert {v[0] for v in fs.values()} == {SURVEY}


def test_deterministic():
    home = home_input(wall_type=None, listed_or_conservation="yes", outdoor_space=None)
    assert feasible_set(home) == feasible_set(home)
