"""Validation and cleaning: HomeInput → CleanHome (BUILD_GUIDE P2.2; inputs to the P2.5 min-info policy).

Order: annualise → MISSING_FIELD and CONFLICT_ROOF_VS_TYPE → impute (floor area, score feature fields,
main_fuel, typical-home energy) → intensity → conflict and outlier rules → rating (one batched
RatingModel call) → sap_estimate. Thresholds come from engine.yaml; imputation tables from P1's
config/generated/imputation.yaml (train split only).

Provenance covers every FEATURE_FIELDS name plus "electricity_kwh" and "gas_kwh":
- value supplied by the user (energy: annual figure or monthly readings) → "user";
- main_fuel inferred from a user-given heating_system → "derived";
- any value filled in here (tables, rating model, typical-home energy, main_fuel from an imputed
  heating_system) → "imputed";
- still None after cleaning (nothing given, nothing to impute from) → "assumed".
Imputed feature fields get an IMPUTED_FIELD flag; imputed energy gets one ENERGY_FROM_TYPICAL_HOMES flag.
INSUFFICIENT_INFO_* flags are added by the orchestrator, not here.
"""

from __future__ import annotations

from typing import Any

from greenhome.config import get_config
from greenhome.contracts import FEATURE_FIELDS, CleanHome, DataFlag, HomeInput
from greenhome.core.annualise import annualise
from greenhome.ml.protocols import RatingModel

_ENERGY_FIELDS = ("electricity_kwh", "gas_kwh")
_HEATING_FUEL = {
    "heat_pump": "electricity",
    "electric_storage": "electricity",
    "electric_direct": "electricity",
    "gas_boiler_condensing": "mains_gas",
    "gas_boiler_old": "mains_gas",
    "other_fuel_boiler": "other",
}
_HOUSE_TYPES = frozenset({"detached", "semi_detached", "terraced", "bungalow"})  # no dwelling above


def band_for_sap(sap: float) -> str:
    """EPC band whose SAP range [lo, next band's lo) contains `sap`; below every range → lowest band."""
    bands = sorted(get_config().engine.sap_bands.items(), key=lambda kv: kv[1][0], reverse=True)
    return next((band for band, (lo, _) in bands if sap >= lo), bands[-1][0])


def anchor_sap(raw_sap: float, band: str | None) -> float:
    """Clip a raw SAP into the stated band's range; with no band, into the overall SAP scale."""
    ranges = get_config().engine.sap_bands
    lo, hi = ranges[band] if band is not None else (min(r[0] for r in ranges.values()),
                                                    max(r[1] for r in ranges.values()))
    return min(max(raw_sap, lo), hi)


def _flag(code: str, severity: str, field: str | None, message: str, **evidence: Any) -> DataFlag:
    return DataFlag(code=code, severity=severity, field=field, message=message, evidence=evidence)


def validate_and_clean(home: HomeInput, rating_model: RatingModel | None = None) -> CleanHome:
    """Clean one home. Never mutates `home`. Makes at most one `rating_model.predict_sap` call."""
    cfg = get_config()
    v = cfg.engine.validation
    imp = cfg.imputation
    energy, flags = annualise(home.energy, home.region)
    h = home.model_copy(deep=True)
    prov: dict[str, str] = {f: "user" for f in FEATURE_FIELDS if getattr(home, f) is not None}
    flags += [_flag("MISSING_FIELD", "info", f, f"{f} was not provided.") for f in FEATURE_FIELDS
              if getattr(home, f) is None]

    if h.roof_type == "dwelling_above" and h.property_type in _HOUSE_TYPES:
        flags.append(_flag("CONFLICT_ROOF_VS_TYPE", "error", "roof_type",
                           f"A {h.property_type} home cannot have a dwelling above; roof type ignored.",
                           roof_type=h.roof_type, property_type=h.property_type))
        h.roof_type = None
        del prov["roof_type"]

    def fill(field: str, value: Any, method: str, provenance: str = "imputed") -> None:
        setattr(h, field, value)
        prov[field] = provenance
        flags.append(_flag("IMPUTED_FIELD", "info", field, f"{field} estimated as {value}.",
                           value=value, method=method))

    # --- imputation ---
    if h.floor_area_m2 is None and h.bedrooms is not None:
        area = imp.floor_area(h.property_type, h.bedrooms)
        if area is not None:
            fill("floor_area_m2", area, "median_by_property_type_and_bedrooms")

    mode = imp.feature_mode(h.age_band, h.property_type)
    for field in v.score_feature_fields:
        if getattr(h, field) is None and field in mode:
            fill(field, mode[field], "mode_by_age_band_and_property_type")

    if h.main_fuel is None and h.heating_system is not None:
        fill("main_fuel", _HEATING_FUEL[h.heating_system], "from_heating_system",
             "derived" if prov.get("heating_system") == "user" else "imputed")

    e_prov = {f: "user" if getattr(energy, f) is not None else "assumed" for f in _ENERGY_FIELDS}
    missing = [f for f in _ENERGY_FIELDS if getattr(energy, f) is None]
    typical = None
    if missing and h.floor_area_m2 is not None:
        typical = imp.typical_energy(h.main_fuel, h.heating_system, h.floor_area_m2)
    if typical is not None:
        values, band = typical
        update: dict[str, Any] = {f: values[f] for f in missing}
        elec = update.get("electricity_kwh", energy.electricity_kwh)
        gas = update.get("gas_kwh", energy.gas_kwh)
        energy = energy.model_copy(update={**update, "purchased_kwh": elec + gas, "source": "imputed"})
        e_prov |= {f: "imputed" for f in missing}
        flags.append(_flag("ENERGY_FROM_TYPICAL_HOMES", "warning", None,
                           "Energy use estimated from typical similar homes.",
                           fuels=missing, main_fuel=h.main_fuel, floor_area_band=band, **update))
    energy_imputed = "imputed" in e_prov.values()

    area = h.floor_area_m2
    intensity = None if energy.purchased_kwh is None or area is None else energy.purchased_kwh / area

    # --- conflict and outlier rules ---
    heat_fuel = _HEATING_FUEL.get(h.heating_system)
    gas = energy.gas_kwh
    if gas is not None and e_prov["gas_kwh"] != "imputed" and prov.get("heating_system") == "user" and (
        (heat_fuel == "mains_gas" and gas < v.gas_heating_min_gas_kwh)
        or (heat_fuel == "electricity" and gas > v.non_gas_heating_max_gas_kwh)
    ):
        flags.append(_flag("CONFLICT_HEATING_VS_GAS", "warning", "gas_kwh",
                           f"Gas use does not match {h.heating_system} heating.",
                           heating_system=h.heating_system, gas_kwh=gas))
    peers = cfg.peers(h.property_type, area) if area is not None else None
    if prov.get("energy_rating") == "user" and not energy_imputed and intensity is not None and (
        (h.energy_rating in {"A", "B"} and intensity > peers["p90"])
        or (h.energy_rating in {"F", "G"} and intensity < peers["p10"])
    ):
        flags.append(_flag("CONFLICT_RATING_VS_USAGE", "info", "energy_rating",
                           "Actual energy use is unusual for this rating; both are kept.",
                           energy_rating=h.energy_rating, intensity_kwh_m2=intensity,
                           peer_p10=peers["p10"], peer_p90=peers["p90"]))
    if h.age_band == "2007_onwards" and prov.get("wall_insulation") == "user" and h.wall_insulation == "none":
        flags.append(_flag("CONFLICT_AGE_VS_INSULATION", "warning", "wall_insulation",
                           "Homes built since 2007 normally have insulated walls.",
                           age_band=h.age_band, wall_insulation=h.wall_insulation))
    if h.bedrooms and area is not None and not (
        v.area_per_bedroom_min <= area / h.bedrooms <= v.area_per_bedroom_max
    ):
        flags.append(_flag("OUTLIER_AREA_PER_BEDROOM", "warning", "floor_area_m2",
                           "Floor area is unusual for the number of bedrooms.",
                           floor_area_m2=area, bedrooms=h.bedrooms, area_per_bedroom=area / h.bedrooms))
    if not energy_imputed and intensity is not None and (
        intensity > v.intensity_max_peer_p90_multiple * peers["p90"] or intensity < v.intensity_min_kwh_m2
    ):
        flags.append(_flag("OUTLIER_INTENSITY", "warning", None,
                           "Energy use per m² is far outside the normal range.",
                           intensity_kwh_m2=intensity, peer_p90=peers["p90"]))
    value = h.current_value_gbp
    if value is not None and not (v.value_min_gbp <= value <= v.value_max_gbp):
        flags.append(_flag("OUTLIER_VALUE", "warning", "current_value_gbp",
                           "Property value is outside the expected range.", current_value_gbp=value))
    if h.main_fuel == "other":
        flags.append(_flag("OUT_OF_SCOPE_FUEL", "warning", "main_fuel",
                           "Savings are only modelled for gas and electric homes.", main_fuel=h.main_fuel))

    def clean(sap: float | None) -> CleanHome:
        return CleanHome(
            home=h,
            provenance={f: prov.get(f, "assumed") for f in FEATURE_FIELDS} | e_prov,
            energy=energy,
            intensity_kwh_m2=intensity,
            sap_estimate=sap,
            flags=flags,
            in_savings_scope=h.main_fuel != "other",
        )

    # --- rating ---
    if rating_model is None:
        return clean(None)
    raw = rating_model.predict_sap([clean(None)])[0]
    given_band = h.energy_rating
    if given_band is None:
        fill("energy_rating", band_for_sap(raw), "rating_model")
    return clean(anchor_sap(raw, given_band))
