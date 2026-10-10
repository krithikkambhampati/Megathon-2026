"""Unit tests for EPC text -> enum parsing (README P1.3). Strings are real EPC phrasings."""
import pandas as pd
import pytest

from data_pipeline import parse_epc_features as P


def frame(**cols):
    n = max(len(v) for v in cols.values())
    base = {c: [None] * n for c in [
        "PROPERTY_TYPE", "BUILT_FORM", "CONSTRUCTION_AGE_BAND", "MAIN_FUEL", "ROOF_DESCRIPTION",
        "FLAT_TOP_STOREY", "WALLS_DESCRIPTION", "WINDOWS_DESCRIPTION", "GLAZED_TYPE",
        "MULTI_GLAZE_PROPORTION", "MAINHEAT_DESCRIPTION", "MAINHEAT_ENERGY_EFF",
        "MAINHEATCONT_DESCRIPTION", "PHOTO_SUPPLY", "SOLAR_WATER_HEATING_FLAG"]}
    base.update(cols)
    return pd.DataFrame(base)


@pytest.mark.parametrize("ptype,form,expected", [
    ("House", "Semi-Detached", "semi_detached"),
    ("House", "Detached", "detached"),
    ("House", "Mid-Terrace", "terraced"),
    ("House", "Enclosed End-Terrace", "terraced"),
    ("Flat", "Mid-Terrace", "flat"),
    ("Maisonette", "End-Terrace", "maisonette"),
    ("Bungalow", "Detached", "bungalow"),
    ("Park home", "Detached", None),
    ("House", "NO DATA!", None),
])
def test_property_type(ptype, form, expected):
    assert P.parse_property_type(frame(PROPERTY_TYPE=[ptype], BUILT_FORM=[form]))[0] == expected


@pytest.mark.parametrize("raw,expected", [
    ("England and Wales: before 1900", "pre_1900"),
    ("England and Wales: 1930-1949", "1930_1949"),
    ("England and Wales: 1976-1982", "1967_1982"),
    ("England and Wales: 1991-1995", "1983_1995"),
    ("England and Wales: 2003-2006", "1996_2006"),
    ("England and Wales: 2012 onwards", "2007_onwards"),
    ("2019", "2007_onwards"),
    ("NO DATA!", None),
    ("INVALID!", None),
])
def test_age_band(raw, expected):
    assert P.parse_age_band(frame(CONSTRUCTION_AGE_BAND=[raw]))[0] == expected


@pytest.mark.parametrize("raw,expected", [
    ("mains gas (not community)", "mains_gas"),
    ("Gas: mains gas", "mains_gas"),
    ("electricity (not community)", "electricity"),
    ("Electricity: electricity, unspecified tariff", "electricity"),
    ("oil (not community)", "other"),
    ("LPG (not community)", "other"),
    ("mains gas (community)", "other"),
    ("NO DATA!", None),
])
def test_main_fuel(raw, expected):
    assert P.parse_main_fuel(frame(MAIN_FUEL=[raw]))[0] == expected


@pytest.mark.parametrize("raw,age,ptype,top,exp_type,exp_ins", [
    ("Pitched, 270 mm loft insulation", "1950_1966", "semi_detached", None, "pitched_loft", "full"),
    ("Pitched, 100 mm loft insulation", "1950_1966", "semi_detached", None, "pitched_loft", "medium"),
    ("Pitched, 50 mm loft insulation", "1930_1949", "terraced", None, "pitched_loft", "low"),
    ("Pitched, 400+ mm loft insulation", "1930_1949", "detached", None, "pitched_loft", "full"),
    ("Pitched, no insulation (assumed)", "pre_1900", "terraced", None, "pitched_loft", "none"),
    ("Pitched, limited insulation (assumed)", "1930_1949", "terraced", None, "pitched_loft", "low"),
    ("Pitched, insulated (assumed)", "2007_onwards", "detached", None, "pitched_loft", "full"),
    ("Pitched, insulated (assumed)", "1967_1982", "detached", None, "pitched_loft", "medium"),
    ("(another dwelling above)", "1967_1982", "flat", "N", "dwelling_above", None),
    ("(other premises above)", "pre_1900", "flat", "N", "dwelling_above", None),
    ("Flat, no insulation (assumed)", "1950_1966", "flat", "Y", "flat_roof", "none"),
    ("Roof room(s), insulated (assumed)", "pre_1900", "terraced", None, "room_in_roof", "medium"),
    ("Average thermal transmittance 0.11 W/m-¦K", "2007_onwards", "detached", None, "pitched_loft", "full"),
    ("To ar oleddf, 270 mm o inswleiddio yn y llofft", "1950_1966", "semi_detached", None, "pitched_loft", "full"),
    (None, None, "flat", "N", "dwelling_above", None),
])
def test_roof(raw, age, ptype, top, exp_type, exp_ins):
    df = frame(ROOF_DESCRIPTION=[raw], FLAT_TOP_STOREY=[top])
    rt, ri = P.parse_roof(df, pd.Series([age]), pd.Series([ptype]))
    assert rt[0] == exp_type
    assert ri[0] == exp_ins


@pytest.mark.parametrize("raw,age,exp_type,exp_ins", [
    ("Cavity wall, as built, no insulation (assumed)", "1950_1966", "cavity", "none"),
    ("Cavity wall, filled cavity", "1950_1966", "cavity", "full"),
    ("Cavity wall, as built, insulated (assumed)", "1996_2006", "cavity", "full"),
    ("Cavity wall, as built, partial insulation (assumed)", "1983_1995", "cavity", "partial"),
    ("Cavity wall, as built", "1950_1966", "cavity", "none"),
    ("Solid brick, as built, no insulation (assumed)", "pre_1900", "solid", "none"),
    ("Solid brick, with internal insulation", "pre_1900", "solid", "full"),
    ("Solid brick, with external insulation", "1900_1929", "solid", "full"),
    ("Sandstone or limestone, as built, no insulation (assumed)", "pre_1900", "solid", "none"),
    ("Granite or whinstone, as built, no insulation (assumed)", "pre_1900", "solid", "none"),
    ("Timber frame, as built, insulated (assumed)", "2007_onwards", "timber_or_system", "full"),
    ("System built, as built, no insulation (assumed)", "1967_1982", "timber_or_system", "none"),
    ("Average thermal transmittance 0.28 W/m-¦K", "2007_onwards", None, "full"),
    ("Waliau ceudod, fel y'u hadeiladwyd, dim inswleiddio (rhagdybiaeth)", "1950_1966", "cavity", "none"),
])
def test_walls(raw, age, exp_type, exp_ins):
    wt, wi = P.parse_walls(frame(WALLS_DESCRIPTION=[raw]), pd.Series([age]))
    assert wt[0] == exp_type
    assert wi[0] == exp_ins


@pytest.mark.parametrize("win,gt,prop,expected", [
    ("Fully double glazed", "double glazing installed during or after 2002", 100, "double"),
    ("Single glazed", "single glazing", 0, "single"),
    ("Partial double glazing", "double glazing installed before 2002", 50, "partial_double"),
    ("Mostly double glazing", "double glazing installed before 2002", 85, "double"),
    ("Some double glazing", None, 30, "partial_double"),
    ("Full secondary glazing", "secondary glazing", 100, "secondary"),
    ("Fully triple glazed", "triple glazing", 100, "triple"),
    ("High performance glazing", None, 100, "double"),
    ("Multiple glazing throughout", None, 100, "double"),
    (None, "double glazing, unknown install date", 100, "double"),
    (None, None, None, None),
])
def test_glazing(win, gt, prop, expected):
    df = frame(WINDOWS_DESCRIPTION=[win], GLAZED_TYPE=[gt], MULTI_GLAZE_PROPORTION=[prop])
    assert P.parse_glazing(df)[0] == expected


@pytest.mark.parametrize("raw,eff,fuel,expected", [
    ("Boiler and radiators, mains gas", "Good", "mains_gas", "gas_boiler_condensing"),
    ("Boiler and radiators, mains gas", "Very Good", "mains_gas", "gas_boiler_condensing"),
    ("Boiler and radiators, mains gas", "Average", "mains_gas", "gas_boiler_old"),
    ("Boiler and underfloor heating, mains gas", "Good", "mains_gas", "gas_boiler_condensing"),
    ("Room heaters, mains gas", "Average", "mains_gas", "gas_boiler_old"),
    ("Air source heat pump, radiators, electric", "Very Good", "electricity", "heat_pump"),
    ("Ground source heat pump, underfloor, electric", "Very Good", "electricity", "heat_pump"),
    ("Electric storage heaters", "Poor", "electricity", "electric_storage"),
    ("Room heaters, electric", "Very Poor", "electricity", "electric_direct"),
    ("No system present: electric heaters assumed", "Very Poor", "electricity", "electric_direct"),
    ("Boiler and radiators, oil", "Average", "other", "other_fuel_boiler"),
    ("Boiler and radiators, LPG", "Average", "other", "other_fuel_boiler"),
    ("Community scheme", "Good", "other", None),
    ("Boiler and radiators, mains gas, Electric storage heaters", "Good", "mains_gas", "gas_boiler_condensing"),
])
def test_heating(raw, eff, fuel, expected):
    df = frame(MAINHEAT_DESCRIPTION=[raw], MAINHEAT_ENERGY_EFF=[eff])
    assert P.parse_heating(df, pd.Series([fuel]))[0] == expected


@pytest.mark.parametrize("raw,expected", [
    ("Programmer, room thermostat and TRVs", "programmer_thermostat_trvs"),
    ("Time and temperature zone control", "smart_zoned"),
    ("Programmer and room thermostat", "programmer_thermostat"),
    ("Programmer, TRVs and bypass", "programmer_thermostat"),
    ("Programmer, no room thermostat", "timer_only"),
    ("Room thermostat only", "timer_only"),
    ("No time or thermostatic control of room temperature", "none"),
    ("Automatic charge control", "timer_only"),
    ("Manual charge control", "none"),
    ("Controls for high heat retention storage heaters", "programmer_thermostat"),
    ("Smart thermostat with TRVs", "smart_thermostat"),
])
def test_controls(raw, expected):
    assert P.parse_controls(frame(MAINHEATCONT_DESCRIPTION=[raw]))[0] == expected


@pytest.mark.parametrize("pv,swh,expected", [
    ("0", "N", "none"), ("25", "N", "solar_pv"), ("0", "Y", "solar_thermal"),
    ("30", "Y", "solar_pv"), (None, None, None),
])
def test_renewables(pv, swh, expected):
    assert P.parse_renewables(frame(PHOTO_SUPPLY=[pv], SOLAR_WATER_HEATING_FLAG=[swh]))[0] == expected


@pytest.mark.parametrize("raw,fuel,expected", [
    ("Room heaters, LPG", "other", "other_fuel_boiler"),
    ("Room heaters, smokeless fuel", "other", "other_fuel_boiler"),
    ("Warm air, Electricaire", "electricity", "electric_storage"),
    ("Room heaters, radiators, electric", "electricity", "electric_direct"),
    ("Boiler and radiators, mains gas, Room heaters, electric", "mains_gas", "gas_boiler_condensing"),
])
def test_heating_real_data_cases(raw, fuel, expected):
    df = frame(MAINHEAT_DESCRIPTION=[raw], MAINHEAT_ENERGY_EFF=["Good"])
    assert P.parse_heating(df, pd.Series([fuel]))[0] == expected


def test_none_controls_means_no_controls():
    assert P.parse_controls(frame(MAINHEATCONT_DESCRIPTION=["None"]))[0] == "none"


def test_timber_additional_insulation():
    _, wi = P.parse_walls(frame(WALLS_DESCRIPTION=["Timber frame, with additional insulation"]), pd.Series(["1967_1982"]))
    assert wi[0] == "full"


def test_u_value_roof_on_house_is_pitched():
    rt, ri = P.parse_roof(frame(ROOF_DESCRIPTION=["Average thermal transmittance 0.11 W/m²K"]),
                          pd.Series(["2007_onwards"]), pd.Series(["detached"]))
    assert (rt[0], ri[0]) == ("pitched_loft", "full")
