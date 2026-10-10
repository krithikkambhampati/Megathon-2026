"""Demo homes for the "Load example home" dropdown (README P1.10) -> data/examples/*.json + index.json.

Real homes come from the TEST split only (never seen in training), one per scenario the judges may
try. P10001 is the PS2 example home: synthetic, labelled as such, using the reserved id range.
Every file is a HomeInput JSON (README section 7.3): null = "not sure"; missing months are absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
OUT = ROOT / "data" / "examples"
GEN = ROOT / "config" / "generated"

HOME_FIELDS = [
    "property_type",
    "age_band",
    "floor_area_m2",
    "bedrooms",
    "region",
    "current_value_gbp",
    "energy_rating",
    "roof_type",
    "roof_insulation",
    "wall_type",
    "wall_insulation",
    "glazing",
    "heating_system",
    "main_fuel",
    "renewables",
    "smart_controls",
    "listed_or_conservation",
    "outdoor_space",
]


def _clean(v):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


def home_json(row: pd.Series, monthly: pd.DataFrame) -> dict:
    h = {"property_id": row["property_id"], "customer_id": row["customer_id"]}
    for f in HOME_FIELDS:
        h[f] = _clean(row.get(f))
    if h["floor_area_m2"] is not None:
        h["floor_area_m2"] = round(h["floor_area_m2"], 1)
    m = monthly[monthly["property_id"] == row["property_id"]].sort_values("month")
    h["energy"] = {
        "annual_electricity_kwh": _clean(row.get("annual_electricity_kwh")),
        "annual_gas_kwh": _clean(row.get("annual_gas_kwh")),
        "monthly": [
            {
                "month": r.month,
                "electricity_kwh": None if pd.isna(r.electricity_kwh) else round(float(r.electricity_kwh), 1),
                "gas_kwh": None if pd.isna(r.gas_kwh) else round(float(r.gas_kwh), 1),
            }
            for r in m.itertuples()
        ]
        or None,
    }
    return h


def pick(df: pd.DataFrame, mask: pd.Series, key: str | None = None) -> pd.Series:
    cand = df[mask]
    if cand.empty:
        raise ValueError("no candidate for example")
    if key:  # most typical: closest to the median of `key`
        return cand.iloc[(cand[key] - cand[key].median()).abs().argsort().iloc[0]]
    return cand.iloc[0]


def main() -> None:
    props = pd.read_parquet(PROCESSED / "properties.parquet")
    splits = pd.read_parquet(PROCESSED / "splits.parquet")
    monthly = pd.read_parquet(PROCESSED / "energy_monthly.parquet")
    peers = pd.read_parquet(GEN / "peer_percentiles.parquet")
    test = props[props["property_id"].isin(splits.loc[splits["split"] == "test", "property_id"])].copy()

    ann = monthly.groupby("property_id")[["electricity_kwh", "gas_kwh"]].sum(min_count=1)
    nmon = monthly.groupby("property_id").size()
    test = test.join(ann.rename(columns=lambda c: "m_" + c), on="property_id").join(
        nmon.rename("n_months"), on="property_id"
    )
    test["intensity"] = (test["m_electricity_kwh"].fillna(0) + test["m_gas_kwh"].fillna(0)) / test[
        "floor_area_m2"
    ]
    test["band"] = pd.cut(
        test["floor_area_m2"],
        [0, 50, 90, 130, 200, np.inf],
        labels=["<50", "50-90", "90-130", "130-200", ">200"],
    ).astype(str)
    test = test.merge(
        peers[["property_type", "floor_area_band", "p10", "p90"]],
        left_on=["property_type", "band"],
        right_on=["property_type", "floor_area_band"],
        how="left",
    )
    complete = test["missingness_pattern"].eq("complete")
    winter = {"-12", "-01", "-02"}
    no_winter = monthly[monthly["month"].str[-3:].isin(winter)].groupby("property_id").size()
    test["has_winter"] = test["property_id"].map(no_winter).fillna(0) > 0

    examples = [
        (
            "Typical poor gas home",
            "Rating E/F semi with old boiler and single glazing",
            pick(
                test,
                complete
                & test.energy_rating.isin(["E", "F"])
                & test.heating_system.eq("gas_boiler_old")
                & test.glazing.isin(["single", "partial_double"])
                & test.property_type.eq("semi_detached"),
                "intensity",
            ),
        ),
        (
            "Large but efficient detached",
            "Over 200 m2, rating B/C: big total use must not mean inefficient",
            pick(
                test,
                complete
                & (test.floor_area_m2 > 200)
                & test.energy_rating.isin(["B", "C"])
                & test.property_type.eq("detached"),
                "intensity",
            ),
        ),
        (
            "Flat with a dwelling above",
            "No loft, so loft insulation and solar are infeasible",
            pick(
                test,
                complete
                & test.property_type.eq("flat")
                & test.roof_type.eq("dwelling_above")
                & test.heating_system.eq("gas_boiler_condensing"),
                "intensity",
            ),
        ),
        (
            "Missing winter meter readings",
            "Gaps over Dec-Feb: seasonal annualisation, not mean x 12",
            pick(
                test,
                test.missingness_pattern.eq("block_gap")
                & ~test.has_winter
                & test.heating_system.str.startswith("gas"),
            ),
        ),
        (
            "Good rating, very high usage",
            "Rated B/C, but uses more than 90% of similar homes (flagged as high use for its size)",
            pick(test, complete & test.energy_rating.isin(["B", "C"]) & (test.intensity > test.p90)),
        ),
        (
            "Heat pump home",
            "Already electrified: heat pump infeasible, focus on fabric/solar",
            pick(test, complete & test.heating_system.eq("heat_pump")),
        ),
        (
            "Home with solar PV",
            "Solar cuts grid imports, not demand",
            pick(test, complete & test.renewables.eq("solar_pv") & test.heating_system.str.startswith("gas")),
        ),
        (
            "Electric storage heater flat",
            "Electric heating, no gas: per-fuel results differ",
            pick(
                test,
                complete & test.property_type.eq("flat") & test.heating_system.eq("electric_storage"),
                "intensity",
            ),
        ),
        (
            "Solid-wall Victorian terrace",
            "Pre-1900 solid walls: solid wall insulation feasible but costly",
            pick(
                test,
                complete
                & test.age_band.eq("pre_1900")
                & test.wall_type.eq("solid")
                & test.wall_insulation.eq("none")
                & test.property_type.eq("terraced"),
                "intensity",
            ),
        ),
        (
            "Gas meter data missing",
            "Gas-heated, but the gas column is missing",
            pick(
                test, test.missingness_pattern.eq("gas_missing") & test.heating_system.str.startswith("gas")
            ),
        ),
    ]
    # added 2026-10-11: fill gaps in the catalogue (Very poor, maisonette, London, North, A-rated)
    examples += [
        (
            "Very poor electric home",
            "Rated G with direct electric heating: the bottom of the scale",
            pick(
                test,
                complete & test.energy_rating.eq("G") & test.heating_system.eq("electric_direct"),
                "intensity",
            ),
        ),
        (
            "Maisonette",
            "A two-storey flat with its own entrance, heated by gas",
            pick(
                test,
                complete
                & test.property_type.eq("maisonette")
                & test.heating_system.eq("gas_boiler_condensing"),
                "intensity",
            ),
        ),
        (
            "London terrace",
            "A pre-1900 London terrace with solid walls",
            pick(
                test,
                complete
                & test.region.eq("london")
                & test.property_type.eq("terraced")
                & test.age_band.eq("pre_1900"),
                "intensity",
            ),
        ),
        (
            "Insulate first",
            "Empty loft and unfilled cavity walls: insulation comes before a heat pump",
            pick(
                test,
                complete
                & test.region.isin(["north_west", "north_east"])
                & test.property_type.eq("semi_detached")
                & test.roof_insulation.eq("none")
                & test.wall_type.eq("cavity")
                & test.wall_insulation.eq("none")
                & test.heating_system.str.startswith("gas"),
                "intensity",
            ),
        ),
        (
            "A-rated home",
            "Rated A, but still gas heated: the score looks beyond the EPC rating",
            pick(test, complete & test.energy_rating.eq("A"), "intensity"),
        ),
        (
            "Solar water heating",
            "Solar thermal panels heat water; they are not solar electricity",
            pick(
                test,
                complete & test.renewables.eq("solar_thermal") & test.heating_system.str.startswith("gas"),
            ),
        ),
        (
            "Only yearly totals",
            "No monthly readings, just a yearly total per fuel",
            pick(
                test, test.missingness_pattern.eq("annual_only") & test.heating_system.str.startswith("gas")
            ),
        ),
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.json"):
        f.unlink()
    index = []
    for title, why, row in examples:
        j = home_json(row, monthly)
        (OUT / f"{row['property_id']}.json").write_text(json.dumps(j, indent=2))
        index.append(
            {"property_id": row["property_id"], "title": title, "why_interesting": why, "synthetic": False}
        )

    # almost no information: a test home with most answers "not sure" and no energy data
    base = pick(test, complete & test.property_type.eq("terraced"))
    j = home_json(base, monthly.iloc[0:0])
    for f in HOME_FIELDS:
        if f not in ("property_type", "region"):
            j[f] = None
    j["energy"] = {"annual_electricity_kwh": None, "annual_gas_kwh": None, "monthly": None}
    (OUT / f"{base['property_id']}_minimal.json").write_text(json.dumps({**j, "property_id": None}, indent=2))
    index.append(
        {
            "property_id": f"{base['property_id']}_minimal",
            "title": "Almost no information",
            "why_interesting": "Only type and region known: app must say what it cannot estimate",
            "synthetic": False,
        }
    )

    # PS2 example home P10001 (synthetic, documented)
    p10001 = {
        "property_id": "P10001",
        "customer_id": "C10001",
        "property_type": "semi_detached",
        "age_band": "1950_1966",
        "floor_area_m2": 85.0,
        "bedrooms": 3,
        "region": "east_midlands",
        "current_value_gbp": 350000.0,
        "energy_rating": "E",
        "roof_type": "pitched_loft",
        "roof_insulation": "low",
        "wall_type": "cavity",
        "wall_insulation": "none",
        "glazing": "single",
        "heating_system": "gas_boiler_condensing",
        "main_fuel": "mains_gas",
        "renewables": "none",
        "smart_controls": "programmer_thermostat",
        "listed_or_conservation": "no",
        "outdoor_space": "yes",
        "energy": {"annual_electricity_kwh": 4800.0, "annual_gas_kwh": 12000.0, "monthly": None},
    }
    (OUT / "P10001.json").write_text(json.dumps(p10001, indent=2))
    index.insert(
        0,
        {
            "property_id": "P10001",
            "title": "PS2 example home (P10001)",
            "why_interesting": "The brief's example: rating E, high use, no solar, poor insulation, "
            "gas boiler, single glazing",
            "synthetic": True,
        },
    )
    (OUT / "index.json").write_text(json.dumps(index, indent=2))
    for e in index:
        print(f"{e['property_id']:>16}  {e['title']}")


if __name__ == "__main__":
    main()
