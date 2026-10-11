"""Shared model features: the ONE place model inputs are built, for training AND inference
(BUILD_GUIDE section 7.1 "Feature building" and P2.3). Part 2 should import this, never re-implement it.

Input: a pandas DataFrame with contract columns (BUILD_GUIDE 7.2/7.3 HomeInput field names; null = unknown).
Only fields that exist in HomeInput are used, so every model can be served from what the app knows.
(EPC-only fields such as habitable rooms or local authority are deliberately NOT features.)

Encodings are fixed here (category lists and ordinal maps), so a trained model and the app always see
identical columns in identical order. LightGBM handles NaN natively, so unknown answers stay NaN.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
_REGIONS = yaml.safe_load((ROOT / "config" / "regions.yaml").read_text())["regions"]

CATEGORIES = {
    "property_type": ["detached", "semi_detached", "terraced", "flat", "bungalow", "maisonette"],
    "region": [
        "north_east",
        "north_west",
        "yorkshire_humber",
        "east_midlands",
        "west_midlands",
        "east_of_england",
        "london",
        "south_east",
        "south_west",
        "wales",
    ],
    "wall_type": ["cavity", "solid", "timber_or_system"],
    "roof_type": ["pitched_loft", "flat_roof", "room_in_roof", "dwelling_above"],
    "heating_system": [
        "heat_pump",
        "gas_boiler_condensing",
        "gas_boiler_old",
        "electric_storage",
        "electric_direct",
        "other_fuel_boiler",
    ],
    "main_fuel": ["mains_gas", "electricity", "other"],
}
ORDINALS = {  # higher = better / more efficient state (BUILD_GUIDE P2.4 orderings)
    "age_band": [
        "pre_1900",
        "1900_1929",
        "1930_1949",
        "1950_1966",
        "1967_1982",
        "1983_1995",
        "1996_2006",
        "2007_onwards",
    ],
    "roof_insulation": ["none", "low", "medium", "full"],
    "wall_insulation": ["none", "partial", "full"],
    "glazing": ["single", "partial_double", "secondary", "double", "triple"],
    "smart_controls": [
        "none",
        "timer_only",
        "programmer_thermostat",
        "programmer_thermostat_trvs",
        "smart_thermostat",
        "smart_zoned",
    ],
    "renewables": ["none", "solar_thermal", "solar_pv", "solar_pv_battery"],
    "energy_rating": ["G", "F", "E", "D", "C", "B", "A"],
    # heating efficiency rank, ordered by the REAL median SAP gain when switching to a heat pump from each
    # system (repeat EPCs: direct electric +37, other fuel +26, storage +20, old gas +19, condensing gas +7)
    "heating_system": [
        "electric_direct",
        "electric_storage",
        "other_fuel_boiler",
        "gas_boiler_old",
        "gas_boiler_condensing",
        "heat_pump",
    ],
}
RETROFITS = [
    "loft_insulation",
    "cavity_wall_insulation",
    "solid_wall_insulation",
    "double_glazing",
    "air_source_heat_pump",
    "solar_pv",
    "smart_thermostat",
]
QUALITY = [
    "roof_insulation_ord",
    "wall_insulation_ord",
    "glazing_ord",
    "smart_controls_ord",
    "renewables_ord",
]
RATING_QUALITY = QUALITY + ["heating_ord"]


# For model features a smart thermostat counts as the same control level as time+temperature zone
# control: EPC (RdSAP) has almost no "smart thermostat" level, and zone control is what a controls
# upgrade achieves in EPC terms (real repeat-EPC gain ~+4 SAP).
_ORD_OVERRIDE = {"smart_controls": {"smart_thermostat": 5}}


def _ord(s: pd.Series, levels: list[str], name: str | None = None) -> pd.Series:
    m = {v: i for i, v in enumerate(levels)}
    m.update(_ORD_OVERRIDE.get(name, {}))
    return s.map(m).astype("float64")


def _cat(s: pd.Series, levels: list[str]) -> pd.Series:
    return pd.Categorical(s.where(s.isin(levels)), categories=levels)


def home_features(df: pd.DataFrame) -> pd.DataFrame:
    """Features describing the home itself (shared by every model)."""
    out = pd.DataFrame(index=df.index)
    for c, levels in CATEGORIES.items():
        out[c] = _cat(df[c] if c in df else pd.Series(np.nan, index=df.index), levels)
    out["age_ord"] = _ord(df["age_band"], ORDINALS["age_band"])
    out["floor_area_m2"] = pd.to_numeric(df["floor_area_m2"], errors="coerce")
    out["log_floor_area"] = np.log(out["floor_area_m2"])
    out["bedrooms"] = pd.to_numeric(df.get("bedrooms"), errors="coerce").astype("float64")
    for c in ["roof_insulation", "wall_insulation", "glazing", "smart_controls", "renewables"]:
        out[f"{c}_ord"] = _ord(df[c], ORDINALS[c], c)
    out["roof_exposed"] = (
        (~df["roof_type"].eq("dwelling_above")).astype("float64").where(df["roof_type"].notna())
    )
    out["gas_connected"] = (
        df["gas_connected"].astype("float64")
        if "gas_connected" in df
        else df["main_fuel"].eq("mains_gas").astype("float64")
    )
    out["hdd_factor"] = df["region"].map({r: v["hdd_factor"] for r, v in _REGIONS.items()}).astype("float64")
    out["pv_yield"] = (
        df["region"].map({r: v["pv_yield_kwh_per_kwp"] for r, v in _REGIONS.items()}).astype("float64")
    )
    return out


def package_flags(packages: list[frozenset[str]] | pd.DataFrame, index) -> pd.DataFrame:
    """r_<retrofit> 0/1 columns, from a list of packages or from existing r_* boolean columns."""
    if isinstance(packages, pd.DataFrame):
        return pd.DataFrame(
            {f"r_{r}": packages[f"r_{r}"].astype("float64").to_numpy() for r in RETROFITS}, index=index
        )
    return pd.DataFrame({f"r_{r}": [float(r in p) for p in packages] for r in RETROFITS}, index=index)


# ---------------------------------------------------------------- per-model feature sets


def rating_features(df: pd.DataFrame) -> pd.DataFrame:
    """M4 SAP model: home only (the rating is the target). main_fuel is dropped: it duplicates the heating
    system, and after a heat-pump retrofit "electricity" made the model think of storage heaters."""
    f = home_features(df).drop(columns=["main_fuel", "heating_system"])
    # heating as an ordered efficiency rank (monotone +1 in the model) instead of a free category, so a
    # heat pump can never be predicted to LOWER the rating; real gas->heat pump pairs have median +7 SAP
    f["heating_ord"] = _ord(df["heating_system"], ORDINALS["heating_system"])
    return f


def recommender_features(df: pd.DataFrame) -> pd.DataFrame:
    """M2 assessor-relevance model: home + current rating."""
    f = home_features(df)
    f["rating_ord"] = _ord(df["energy_rating"], ORDINALS["energy_rating"])
    return f


# Features a retrofit can change. The value model must not see them: a retrofit may change value only
# through the rating (PS2 section 7: compare before/after "holding other property characteristics constant").
# Seen directly, they carry confounded premiums from sales data (e.g. heat-pump homes are newer).
RETROFIT_CHANGEABLE = [
    "heating_system",
    "main_fuel",
    "roof_insulation_ord",
    "wall_insulation_ord",
    "glazing_ord",
    "smart_controls_ord",
    "renewables_ord",
    "gas_connected",
]


def value_features(
    df: pd.DataFrame, rating: pd.Series, month_index: pd.Series, hpi_index: pd.Series
) -> pd.DataFrame:
    """M3 hedonic value model: structure + location + rating + market conditions.

    No retrofit-changeable fields: a retrofit changes value only through the rating."""
    f = home_features(df).drop(columns=RETROFIT_CHANGEABLE)
    f["rating_ord"] = _ord(rating, ORDINALS["energy_rating"])
    f["month_index"] = month_index.astype("float64").to_numpy()  # months since 2015-01
    f["hpi_region_index"] = hpi_index.astype("float64").to_numpy()
    return f


def energy_features(
    df: pd.DataFrame, elec_before: pd.Series, gas_before: pd.Series, packages
) -> pd.DataFrame:
    """M1 post-retrofit energy model: home + annual baseline per fuel + package flags."""
    f = home_features(df)
    e, g = elec_before.astype("float64").to_numpy(), gas_before.astype("float64").to_numpy()
    tot = e + g
    f["log_elec_before"] = np.log1p(e)
    f["log_gas_before"] = np.log1p(g)
    f["elec_share"] = np.where(tot > 0, e / np.where(tot > 0, tot, 1), np.nan)
    f["intensity_before"] = tot / f["floor_area_m2"].to_numpy()
    return pd.concat([f, package_flags(packages, df.index)], axis=1)


# retrofits that physically cannot change a fuel are hidden from that fuel's model (set to 0), so
# training noise can never create an effect (e.g. solar PV "cutting" gas use)
FUEL_IRRELEVANT = {"gas": ["r_solar_pv"], "elec": []}
FUEL_IRRELEVANT_RETROFITS = {f: [c[2:] for c in cols] for f, cols in FUEL_IRRELEVANT.items()}


def mask_for_fuel(X: pd.DataFrame, fuel: str) -> pd.DataFrame:
    X = X.copy()
    for c in FUEL_IRRELEVANT[fuel]:
        X[c] = 0.0
    return X


def monotone_constraints(columns: list[str], spec: dict[str, int]) -> list[int]:
    return [spec.get(c, 0) for c in columns]
