from __future__ import annotations

import pytest
from conftest import home_input

from greenhome.config import get_config
from greenhome.contracts import FEATURE_FIELDS, CleanHome
from greenhome.core.validate import anchor_sap, band_for_sap, validate_and_clean

CFG = get_config()
V = CFG.engine.validation
IMP = CFG.imputation


class FakeRating:
    version = "fake-0"

    def __init__(self, sap: float) -> None:
        self.sap = sap
        self.calls: list[list[CleanHome]] = []

    def predict_sap(self, homes: list[CleanHome]) -> list[float]:
        self.calls.append(homes)
        return [self.sap] * len(homes)


def _codes(clean: CleanHome) -> list[str]:
    return [f.code for f in clean.flags]


def _flag(clean: CleanHome, code: str):
    return next(f for f in clean.flags if f.code == code)


def _energy(elec: float | None, gas: float | None) -> dict:
    return {"annual_electricity_kwh": elec, "annual_gas_kwh": gas}


# ---------- SAP bands ----------
@pytest.mark.parametrize(("sap", "band"), [
    (100, "A"), (150, "A"), (92, "A"), (91.5, "B"), (81, "B"), (80.99, "C"), (69, "C"),
    (55, "D"), (54.5, "E"), (39, "E"), (21, "F"), (20.5, "G"), (1, "G"), (0.2, "G"), (-5, "G"),
])
def test_band_for_sap(sap, band):
    assert band_for_sap(sap) == band


@pytest.mark.parametrize(("raw", "band", "out"), [
    (60, "E", 54), (30, "E", 39), (45.5, "E", 45.5), (39, "E", 39), (54, "E", 54),
    (150, None, 100), (-3, None, 1), (61.25, None, 61.25), (95, "A", 95), (99, "B", 91),
])
def test_anchor_sap(raw, band, out):
    assert anchor_sap(raw, band) == out


# ---------- clean baseline ----------
def test_p10001_is_clean():
    clean = validate_and_clean(home_input())
    assert clean.flags == []
    assert set(clean.provenance) == set(FEATURE_FIELDS) | {"electricity_kwh", "gas_kwh"}
    assert set(clean.provenance.values()) == {"user"}
    assert clean.energy.purchased_kwh == 16800
    assert clean.intensity_kwh_m2 == pytest.approx(16800 / 85)
    assert clean.sap_estimate is None
    assert clean.in_savings_scope is True
    assert clean.home == home_input()


def test_input_not_mutated():
    home = home_input(floor_area_m2=None, glazing=None, heating_system=None, main_fuel=None,
                      energy_rating=None, roof_type="dwelling_above", energy=_energy(None, None))
    before = home.model_dump()
    validate_and_clean(home, FakeRating(60))
    assert home.model_dump() == before


def test_missing_fields_flagged_and_assumed():
    clean = validate_and_clean(home_input(listed_or_conservation=None, outdoor_space=None, region=None))
    missing = [f for f in clean.flags if f.code == "MISSING_FIELD"]
    assert [f.field for f in missing] == ["region", "listed_or_conservation", "outdoor_space"]
    assert all(f.severity == "info" for f in missing)
    assert clean.provenance["outdoor_space"] == "assumed"
    assert clean.home.outdoor_space is None


# ---------- imputation ----------
def test_roof_conflict_nulls_then_imputes():
    clean = validate_and_clean(home_input(roof_type="dwelling_above"))
    flag = _flag(clean, "CONFLICT_ROOF_VS_TYPE")
    assert flag.severity == "error" and flag.field == "roof_type"
    assert clean.home.roof_type == IMP.feature_mode("1950_1966", "semi_detached")["roof_type"]
    assert clean.provenance["roof_type"] == "imputed"
    assert "IMPUTED_FIELD" in _codes(clean)


def test_flat_with_dwelling_above_is_fine():
    clean = validate_and_clean(home_input(property_type="flat", roof_type="dwelling_above"))
    assert "CONFLICT_ROOF_VS_TYPE" not in _codes(clean)
    assert clean.home.roof_type == "dwelling_above"


@pytest.mark.parametrize(("ptype", "beds"), [("semi_detached", 3), ("flat", 2), ("detached", 15), (None, 1)])
def test_floor_area_imputed(ptype, beds):
    clean = validate_and_clean(home_input(property_type=ptype, bedrooms=beds, floor_area_m2=None))
    assert clean.home.floor_area_m2 == IMP.floor_area(ptype, beds)
    assert clean.provenance["floor_area_m2"] == "imputed"
    flag = next(f for f in clean.flags if f.code == "IMPUTED_FIELD" and f.field == "floor_area_m2")
    assert flag.evidence["value"] == IMP.floor_area(ptype, beds)


def test_floor_area_table_lookups():
    table = IMP.floor_area_by_type_bedrooms
    assert IMP.floor_area("semi_detached", 3) == table["semi_detached"]["3"]["median_m2"]
    assert IMP.floor_area("detached", 15) == table["detached"]["5+"]["median_m2"]  # 5+ bucket
    assert IMP.floor_area("flat", 0) == table["flat"]["1"]["median_m2"]  # studios use the 1-bed row
    rows = [t["2"] for t in table.values()]  # unknown type → n-weighted mean over types
    expected = sum(r["median_m2"] * r["n"] for r in rows) / sum(r["n"] for r in rows)
    assert IMP.floor_area(None, 2) == pytest.approx(expected)


def test_floor_area_unknown_without_bedrooms():
    clean = validate_and_clean(home_input(bedrooms=None, floor_area_m2=None))
    assert clean.home.floor_area_m2 is None
    assert clean.provenance["floor_area_m2"] == "assumed"
    assert clean.intensity_kwh_m2 is None


def test_feature_modes_from_age_type_cell():
    clean = validate_and_clean(home_input(
        age_band="1900_1929", property_type="terraced", wall_type=None, glazing=None, roof_type=None,
    ))
    cell = IMP.feature_mode_by_age_type["1900_1929"]["terraced"]
    for field in ("wall_type", "glazing", "roof_type"):
        assert getattr(clean.home, field) == cell[field]["value"]
    imputed = {f.field: f.evidence for f in clean.flags if f.code == "IMPUTED_FIELD"}
    assert set(imputed) == {"wall_type", "glazing", "roof_type"}
    assert "method" in imputed["wall_type"]
    assert all(clean.provenance[f] == "imputed" for f in imputed)


def test_unknown_age_band_votes_across_cells():
    clean = validate_and_clean(home_input(age_band=None, wall_insulation=None))
    assert clean.home.wall_insulation == IMP.feature_mode(None, "semi_detached")["wall_insulation"]


def test_feature_mode_votes_weight_by_homes_covered():
    cells = [c for by_type in IMP.feature_mode_by_age_type.values() for c in by_type.values()]
    votes: dict[str, float] = {}
    for c in cells:
        votes[c["glazing"]["value"]] = votes.get(c["glazing"]["value"], 0) + c["n"] * c["glazing"]["share"]
    assert IMP.feature_mode(None, None)["glazing"] == max(votes, key=votes.get)


def test_main_fuel_derived_from_user_heating():
    home = home_input(heating_system="heat_pump", main_fuel=None, energy=_energy(6000, 0))
    clean = validate_and_clean(home)
    assert clean.home.main_fuel == "electricity"
    assert clean.provenance["main_fuel"] == "derived"
    assert any(f.code == "IMPUTED_FIELD" and f.field == "main_fuel" for f in clean.flags)


def test_main_fuel_imputed_from_imputed_heating():
    clean = validate_and_clean(home_input(heating_system=None, main_fuel=None))
    assert clean.home.heating_system == IMP.feature_mode("1950_1966", "semi_detached")["heating_system"]
    assert clean.home.main_fuel == "mains_gas"
    assert clean.provenance["main_fuel"] == "imputed"


def test_typical_energy_imputed():
    clean = validate_and_clean(home_input(energy=_energy(None, None)))
    typical, _ = IMP.typical_energy("mains_gas", "gas_boiler_condensing", 85.0)
    assert clean.energy.electricity_kwh == typical["electricity_kwh"]
    assert clean.energy.gas_kwh == typical["gas_kwh"]
    assert clean.energy.purchased_kwh == typical["electricity_kwh"] + typical["gas_kwh"]
    assert clean.energy.source == "imputed"
    assert clean.provenance["electricity_kwh"] == clean.provenance["gas_kwh"] == "imputed"
    assert clean.intensity_kwh_m2 == pytest.approx(clean.energy.purchased_kwh / 85)
    flag = _flag(clean, "ENERGY_FROM_TYPICAL_HOMES")
    assert flag.severity == "warning" and flag.evidence["fuels"] == ["electricity_kwh", "gas_kwh"]


def test_typical_energy_tables():
    et = IMP.energy_typical
    gas, band = IMP.typical_energy("mains_gas", None, 50.0)  # NEED bands are upper-edge inclusive
    assert band == "<50" and gas["gas_kwh"] == et.gas_homes_need_median_kwh_by_floor_area["gas"]["<50"]
    elec, band = IMP.typical_energy("electricity", "heat_pump", 120.0)
    table = et.electric_heated_homes_synthetic_median_electricity_kwh["heat_pump"]
    assert (elec["gas_kwh"], elec["electricity_kwh"]) == (0.0, table[band]["median_kwh"])
    sparse = et.electric_heated_homes_synthetic_median_electricity_kwh["electric_direct"]
    if ">200" not in sparse:  # P1 drops cells with n < 30 → nearest existing band
        _, band = IMP.typical_energy("electricity", "electric_direct", 300.0)
        assert band in sparse
    assert IMP.typical_energy("other", "other_fuel_boiler", 80.0) is None
    assert IMP.typical_energy("electricity", None, 80.0) is None


def test_typical_energy_only_for_missing_fuel():
    clean = validate_and_clean(home_input(energy=_energy(4800, None)))
    assert clean.energy.electricity_kwh == 4800
    assert clean.provenance["electricity_kwh"] == "user"
    assert clean.provenance["gas_kwh"] == "imputed"
    assert clean.energy.purchased_kwh == 4800 + clean.energy.gas_kwh
    assert _flag(clean, "ENERGY_FROM_TYPICAL_HOMES").evidence["fuels"] == ["gas_kwh"]


def test_other_fuel_out_of_scope_and_no_energy_imputation():
    clean = validate_and_clean(home_input(heating_system="other_fuel_boiler", main_fuel="other",
                                          energy=_energy(None, None)))
    assert clean.in_savings_scope is False
    assert clean.energy.purchased_kwh is None and clean.energy.source == "none"
    assert clean.provenance["gas_kwh"] == "assumed"
    assert "OUT_OF_SCOPE_FUEL" in _codes(clean)
    assert "ENERGY_FROM_TYPICAL_HOMES" not in _codes(clean)


# ---------- conflict and outlier rules ----------
@pytest.mark.parametrize(("heating", "fuel", "gas", "fires"), [
    ("gas_boiler_condensing", "mains_gas", V.gas_heating_min_gas_kwh - 1, True),
    ("gas_boiler_old", "mains_gas", V.gas_heating_min_gas_kwh, False),
    ("heat_pump", "electricity", V.non_gas_heating_max_gas_kwh + 1, True),
    ("electric_storage", "electricity", V.non_gas_heating_max_gas_kwh, False),
    ("other_fuel_boiler", "other", 0, False),
])
def test_conflict_heating_vs_gas(heating, fuel, gas, fires):
    clean = validate_and_clean(home_input(heating_system=heating, main_fuel=fuel, energy=_energy(4800, gas)))
    assert ("CONFLICT_HEATING_VS_GAS" in _codes(clean)) is fires


def test_heating_vs_gas_skipped_when_gas_imputed():
    clean = validate_and_clean(home_input(heating_system="heat_pump", main_fuel="mains_gas",
                                          energy=_energy(4800, None)))
    assert "CONFLICT_HEATING_VS_GAS" not in _codes(clean)


def test_heating_vs_gas_skipped_when_heating_imputed():
    # An imputed gas boiler must not contradict a real all-electric home's zero gas.
    clean = validate_and_clean(home_input(heating_system=None, main_fuel=None, energy=_energy(4800, 0)))
    assert clean.home.heating_system == "gas_boiler_condensing"
    assert "CONFLICT_HEATING_VS_GAS" not in _codes(clean)


@pytest.mark.parametrize(("rating", "gas", "fires"), [
    ("A", 20000, True),   # 291 kWh/m² > p90
    ("B", 12000, False),
    ("G", 3000, True),    # 92 kWh/m² < p10
    ("F", 12000, False),
    ("E", 20000, False),
])
def test_conflict_rating_vs_usage(rating, gas, fires):
    clean = validate_and_clean(home_input(energy_rating=rating, energy=_energy(4800, gas)))
    assert ("CONFLICT_RATING_VS_USAGE" in _codes(clean)) is fires
    if fires:
        assert _flag(clean, "CONFLICT_RATING_VS_USAGE").severity == "info"


def test_rating_vs_usage_skipped_when_energy_imputed():
    # Typical-home energy for 20 m² gives an intensity above peer p90, which would conflict with rating A.
    clean = validate_and_clean(home_input(energy_rating="A", energy=_energy(None, None),
                                          floor_area_m2=20.0, bedrooms=1))
    assert clean.intensity_kwh_m2 > CFG.peers("semi_detached", 20.0)["p90"]
    assert "CONFLICT_RATING_VS_USAGE" not in _codes(clean)


@pytest.mark.parametrize(("age", "wall", "fires"), [
    ("2007_onwards", "none", True), ("2007_onwards", "full", False), ("1950_1966", "none", False),
])
def test_conflict_age_vs_insulation(age, wall, fires):
    clean = validate_and_clean(home_input(age_band=age, wall_insulation=wall))
    assert ("CONFLICT_AGE_VS_INSULATION" in _codes(clean)) is fires


@pytest.mark.parametrize(("area", "beds", "fires"), [
    (V.area_per_bedroom_max + 1, 1, True), (V.area_per_bedroom_max, 1, False),
    (V.area_per_bedroom_min * 3 - 1, 3, True), (85.0, 0, False),
])
def test_outlier_area_per_bedroom(area, beds, fires):
    clean = validate_and_clean(home_input(floor_area_m2=area, bedrooms=beds))
    assert ("OUTLIER_AREA_PER_BEDROOM" in _codes(clean)) is fires


@pytest.mark.parametrize(("elec", "gas", "fires"), [
    (4800, 80000, True),   # ~1000 kWh/m² > 3 × p90
    (300, 400, True),      # ~8 kWh/m² < minimum
    (4800, 12000, False),
])
def test_outlier_intensity(elec, gas, fires):
    clean = validate_and_clean(home_input(energy=_energy(elec, gas)))
    assert ("OUTLIER_INTENSITY" in _codes(clean)) is fires


@pytest.mark.parametrize(("value", "fires"), [
    (V.value_min_gbp - 1, True), (V.value_max_gbp + 1, True), (V.value_min_gbp, False), (350000.0, False),
])
def test_outlier_value(value, fires):
    clean = validate_and_clean(home_input(current_value_gbp=value))
    assert ("OUTLIER_VALUE" in _codes(clean)) is fires


# ---------- rating ----------
def test_rating_imputed_from_model():
    model = FakeRating(60.0)
    clean = validate_and_clean(home_input(energy_rating=None), model)
    assert len(model.calls) == 1 and len(model.calls[0]) == 1
    assert clean.home.energy_rating == "D"
    assert clean.provenance["energy_rating"] == "imputed"
    assert clean.sap_estimate == 60.0
    flag = next(f for f in clean.flags if f.code == "IMPUTED_FIELD" and f.field == "energy_rating")
    assert flag.evidence["value"] == "D"


def test_sap_anchored_to_user_band():
    model = FakeRating(60.0)
    clean = validate_and_clean(home_input(), model)
    assert len(model.calls) == 1
    assert clean.home.energy_rating == "E" and clean.provenance["energy_rating"] == "user"
    assert clean.sap_estimate == CFG.engine.sap_bands["E"][1]


def test_no_rating_model_leaves_rating_unknown():
    clean = validate_and_clean(home_input(energy_rating=None))
    assert clean.home.energy_rating is None
    assert clean.provenance["energy_rating"] == "assumed"
    assert clean.sap_estimate is None


def test_deterministic():
    home = home_input(glazing=None, energy=_energy(None, 1000), energy_rating=None, current_value_gbp=1.0e8)
    assert validate_and_clean(home, FakeRating(70)) == validate_and_clean(home, FakeRating(70))
