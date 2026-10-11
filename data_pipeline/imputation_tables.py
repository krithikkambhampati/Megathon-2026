"""Imputation tables for "not sure" answers (BUILD_GUIDE P2.2: "P1 supplies it").

All fitted on TRAIN-split data only. Written to config/generated/imputation.yaml so Part 2 can load
them without pandas/parquet. Every value is labelled with its basis and sample size.

  floor_area_by_type_bedrooms   median floor area (m2) by property_type x bedrooms (1..5+)
  feature_mode_by_age_type      most common value of each feature by age_band x property_type, plus
                                the share it covers (so the UI can say how confident the guess is)
  energy_typical                NEED 2024 median annual gas/electricity by property_type x floor-area band
                                (gas homes) and electricity for electrically heated homes from our
                                calibrated synthetic train homes (NEED has no heating-type split)
  rating_by_age_type            modal EPC band by age_band x property_type (fallback only; M4 preferred)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
REF = PROCESSED / "reference"
OUT = ROOT / "config" / "generated" / "imputation.yaml"
FEATURES = [
    "roof_type",
    "roof_insulation",
    "wall_type",
    "wall_insulation",
    "glazing",
    "heating_system",
    "smart_controls",
    "renewables",
    "main_fuel",
]
NEED_FA_BAND = {
    "50 or less": "<50",
    "51 - 100": "50-100",
    "101 - 150": "100-150",
    "151 - 200": "150-200",
    "Over 200": ">200",
}


def main() -> None:
    splits = pd.read_parquet(PROCESSED / "splits.parquet")
    train_ids = set(splits.loc[splits["split"] == "train", "property_id"])
    certs = pd.read_parquet(PROCESSED / "epc_certificates_model.parquet")
    latest = certs.sort_values("lodgement_date").drop_duplicates("property_id", keep="last")
    tr = latest[latest["property_id"].isin(train_ids)].copy()

    # floor area by type x bedrooms
    tr["beds"] = tr["bedrooms"].clip(upper=5).astype("Int64")
    fa = (
        tr.dropna(subset=["property_type", "beds"])
        .groupby(["property_type", "beds"])["floor_area_m2"]
        .agg(["median", "size"])
    )
    floor_area = {
        pt: {
            ("5+" if int(b) == 5 else str(int(b))): {
                "median_m2": round(float(r["median"]), 1),
                "n": int(r["size"]),
            }
            for b, r in g.droplevel(0).iterrows()
        }
        for pt, g in fa.groupby(level=0)
    }

    # feature modes by age x type
    modes: dict = {}
    for (age, pt), g in tr.dropna(subset=["age_band", "property_type"]).groupby(
        ["age_band", "property_type"]
    ):
        entry = {"n": int(len(g))}
        for f in FEATURES:
            vc = g[f].value_counts(normalize=True)
            if len(vc):
                entry[f] = {"value": vc.index[0], "share": round(float(vc.iloc[0]), 3)}
        r = g["energy_rating"].value_counts(normalize=True)
        entry["energy_rating"] = {"value": r.index[0], "share": round(float(r.iloc[0]), 3)}
        modes.setdefault(age, {})[pt] = entry

    # typical energy: NEED medians (gas homes) by property type and by floor-area band
    h = pd.read_parquet(REF / "need_headline.parquet")
    latest_year = int(h["year"].max())
    need = h[(h["metric"] == "median") & (h["year"] == latest_year) & h["fuel"].isin(["gas", "electricity"])]
    by_fa = {
        f: {
            NEED_FA_BAND[c]: round(float(v), 0)
            for c, v in need[(need.fuel == f) & (need.dimension == "floor_area_band")][
                ["category", "value"]
            ].values
            if c in NEED_FA_BAND
        }
        for f in ["gas", "electricity"]
    }
    # electric-heated homes: from calibrated synthetic train homes (documented as model-based)
    props = pd.read_parquet(PROCESSED / "properties.parquet")
    true = pd.read_parquet(PROCESSED / "labels" / "true_annual_energy.parquet")
    pe = props.merge(true, on="property_id")
    pe = pe[pe["property_id"].isin(train_ids)]
    pe["fa_band"] = pd.cut(
        pe["floor_area_m2"],
        [0, 50, 100, 150, 200, np.inf],
        labels=["<50", "50-100", "100-150", "150-200", ">200"],
    ).astype(str)
    elec_heated = pe[pe["heating_system"].isin(["electric_storage", "electric_direct", "heat_pump"])]
    eh = elec_heated.groupby(["heating_system", "fa_band"])["true_annual_electricity_kwh"].agg(
        ["median", "size"]
    )
    elec_heat = {
        hs: {
            b: {"median_kwh": round(float(r["median"]), 0), "n": int(r["size"])}
            for b, r in g.droplevel(0).iterrows()
            if r["size"] >= 30
        }
        for hs, g in eh.groupby(level=0)
    }

    doc = {
        "generated_by": "data_pipeline/imputation_tables.py (do not edit by hand)",
        "basis": (
            f"train split only; latest EPC per property for features; "
            f"NEED {latest_year} medians for gas homes"
        ),
        "floor_area_by_type_bedrooms": floor_area,
        "feature_mode_by_age_type": modes,
        "energy_typical": {
            "gas_homes_need_median_kwh_by_floor_area": by_fa,
            "electric_heated_homes_synthetic_median_electricity_kwh": elec_heat,
            "note": "Use only when no meter data: flag ENERGY_FROM_TYPICAL_HOMES (BUILD_GUIDE P2.2).",
        },
    }
    OUT.write_text(
        "# Generated: imputation tables for 'not sure' answers (BUILD_GUIDE P2.2).\n"
        + yaml.safe_dump(doc, sort_keys=False, width=200)
    )
    print(
        f"wrote {OUT.relative_to(ROOT)}: {len(floor_area)} property types, "
        f"{sum(len(v) for v in modes.values())} age x type cells"
    )
    print("example floor area semi_detached:", floor_area.get("semi_detached"))
    print(
        "example modes 1930_1949 terraced:",
        {
            k: v
            for k, v in modes["1930_1949"]["terraced"].items()
            if k in ("n", "wall_type", "wall_insulation", "glazing", "heating_system")
        },
    )


if __name__ == "__main__":
    main()
