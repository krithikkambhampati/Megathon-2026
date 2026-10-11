"""EPC certificates (interim) -> clean property tables (BUILD_GUIDE P1.2-P1.4).

Steps
  1. basic validity: rating A-G, SAP 1-100 (clip >100), floor area 15-1000 m2, parseable lodgement date
  2. property key: UPRN when present, else md5(postcode | normalised ADDRESS1); deterministic property_id
     (P + 5+ digits) assigned in hash order so ids don't leak address or date order
  3. parse free text -> contract enums (parse_epc_features), region from local authority code
  4. derived: bedrooms = habitable_rooms - 1 (clip >= 1), gas_connected, outdoor_space for houses
  5. outputs
     data/interim/epc_certs_parsed.parquet     all certs + enums + addresses (for PPD join, repeat EPCs)
     data/processed/epc_certificates_model.parquet   all certs, NO addresses, NO SAP-derived columns
     data/interim/properties_latest.parquet    latest in-scope cert per property (pre-sampling)
     reports/epc_parse_coverage.csv, reports/epc_unmatched_values.csv
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from data_pipeline import parse_epc_features as P
from data_pipeline.epc_recommendations import build_labels
from data_pipeline.kernels import feasible_frame as feasible_set

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
REGIONS = yaml.safe_load((ROOT / "config" / "regions.yaml").read_text())

ENUM_COLS = [
    "property_type",
    "age_band",
    "main_fuel",
    "roof_type",
    "roof_insulation",
    "wall_type",
    "wall_insulation",
    "glazing",
    "heating_system",
    "smart_controls",
    "renewables",
]
LEAKY = [
    "ENERGY_CONSUMPTION_CURRENT",
    "CO2_EMISSIONS_CURRENT",
    "HEATING_COST_CURRENT",
    "HOT_WATER_COST_CURRENT",
    "LIGHTING_COST_CURRENT",
    "POTENTIAL_ENERGY_RATING",
    "POTENTIAL_ENERGY_EFFICIENCY",
]


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def estimate_bedrooms(df: pd.DataFrame) -> pd.Series:
    """EPC has habitable rooms, not bedrooms. A fixed rule (rooms - 1 or - 2) cannot be right: a semi with
    4 habitable rooms is usually a 3-bed with a through-lounge but sometimes a 2-bed with separate rooms.
    So within each property type we rank homes by (habitable rooms, floor area) and assign bedrooms by
    quantile-matching to NEED's national bedroom distribution for that type. Monotone (a home with more
    rooms/area never gets fewer bedrooms) and the bedroom mix matches NEED by construction."""
    from data_pipeline.calibrate import PTYPE_GROUP

    need = pd.read_parquet(ROOT / "data" / "processed" / "reference" / "need_multi.parquet")
    need = need[(need["year"] == need["year"].max()) & need["property_type"].notna()]
    need["pt"] = need["property_type"].map(PTYPE_GROUP)
    dist = need.groupby(["pt", "bedrooms_n"])["n"].sum()
    out = pd.Series(pd.NA, index=df.index, dtype="Int64")
    pt = df["property_type"].map(PTYPE_GROUP)
    for t, idx in df.groupby(pt).groups.items():
        g = df.loc[idx]
        ok = g["habitable_rooms"].notna()
        if not ok.any() or t not in dist.index.get_level_values(0):
            continue
        order = g[ok].sort_values(["habitable_rooms", "floor_area_m2"], kind="mergesort").index
        q = (np.arange(len(order)) + 0.5) / len(order)
        d = dist.loc[t].sort_index()
        cdf = (d.cumsum() / d.sum()).to_numpy()
        beds = d.index.to_numpy()[np.searchsorted(cdf, q, side="left").clip(max=len(d) - 1)]
        out.loc[order] = beds.astype(int)
    return out


def property_keys(df: pd.DataFrame) -> pd.Series:
    uprn = df["UPRN"].astype("string").str.strip().str.lstrip("0")
    addr = (
        df["POSTCODE"].fillna("").str.upper().str.replace(r"\s+", " ", regex=True)
        + "|"
        + df["ADDRESS1"]
        .fillna("")
        .str.upper()
        .str.replace(r"[^A-Z0-9 ]", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    return pd.Series(
        np.where(uprn.fillna("").ne(""), "U" + uprn.fillna(""), "A" + addr.map(_md5)), index=df.index
    )


def main() -> None:
    # read only what we use; parse in chunks and drop the raw description text afterwards
    keep = [
        "CERT_ID",
        "UPRN",
        "POSTCODE",
        "ADDRESS1",
        "ADDRESS2",
        "ADDRESS3",
        "LOCAL_AUTHORITY",
        "LODGEMENT_DATE",
        "CURRENT_ENERGY_RATING",
        "CURRENT_ENERGY_EFFICIENCY",
        "TOTAL_FLOOR_AREA",
        "NUMBER_HABITABLE_ROOMS",
        "MAINS_GAS_FLAG",
        "TRANSACTION_TYPE",
        "TENURE",
        "FLOOR_LEVEL",
        "FLAT_TOP_STOREY",
    ]
    parse_cols = sorted(
        {
            "PROPERTY_TYPE",
            "BUILT_FORM",
            "CONSTRUCTION_AGE_BAND",
            "MAIN_FUEL",
            "ROOF_DESCRIPTION",
            "FLAT_TOP_STOREY",
            "WALLS_DESCRIPTION",
            "WINDOWS_DESCRIPTION",
            "GLAZED_TYPE",
            "MULTI_GLAZE_PROPORTION",
            "MAINHEAT_DESCRIPTION",
            "MAINHEAT_ENERGY_EFF",
            "MAINHEATCONT_DESCRIPTION",
            "PHOTO_SUPPLY",
            "SOLAR_WATER_HEATING_FLAG",
        }
    )
    pf = pq.ParquetFile(INTERIM / "epc_certificates.parquet")
    n0 = pf.metadata.num_rows
    parts, cov_parts, unmatched_parts = [], [], []
    drop_counts = {"invalid_basic_fields": 0}
    for batch in pf.iter_batches(batch_size=400_000, columns=sorted(set(keep) | set(parse_cols))):
        df = batch.to_pandas()
        df["energy_rating"] = df["CURRENT_ENERGY_RATING"].str.strip().str.upper()
        df["sap_score"] = pd.to_numeric(df["CURRENT_ENERGY_EFFICIENCY"], errors="coerce").clip(upper=100)
        df["floor_area_m2"] = pd.to_numeric(df["TOTAL_FLOOR_AREA"], errors="coerce")
        df["lodgement_date"] = pd.to_datetime(df["LODGEMENT_DATE"].str.slice(0, 10), errors="coerce")
        df["habitable_rooms"] = (
            pd.to_numeric(df["NUMBER_HABITABLE_ROOMS"], errors="coerce").round().astype("Int64")
        )
        valid = (
            df["energy_rating"].isin(list("ABCDEFG"))
            & df["sap_score"].between(1, 100)
            & df["floor_area_m2"].between(15, 1000)
            & df["lodgement_date"].notna()
        )
        drop_counts["invalid_basic_fields"] += int((~valid).sum())
        df = df[valid]
        parsed = P.parse_all(df)
        cov_parts.append(P.coverage(parsed) * len(parsed))
        unmatched_parts.append(P.unmatched_report(df, parsed, top=40))
        parts.append(
            pd.concat(
                [
                    df[
                        keep
                        + ["energy_rating", "sap_score", "floor_area_m2", "lodgement_date", "habitable_rooms"]
                    ],
                    parsed,
                ],
                axis=1,
            )
        )
        print(f"  parsed {sum(len(x) for x in parts):,} / {n0:,}")
    df = pd.concat(parts, ignore_index=True)
    del parts

    REPORTS.mkdir(exist_ok=True)
    cov = (sum(cov_parts) / len(df)).sort_values().rename("coverage").to_frame()
    cov.to_csv(REPORTS / "epc_parse_coverage.csv")
    um = pd.concat(unmatched_parts).groupby(["field", "raw_value"], as_index=False)["count"].sum()
    um.sort_values(["field", "count"], ascending=[True, False]).groupby("field").head(25).to_csv(
        REPORTS / "epc_unmatched_values.csv", index=False
    )
    print("parse coverage (share of certificates mapped to an enum):\n", cov.round(4).to_string())

    # assessor recommendations: retrofit labels + old (non-condensing) boiler evidence
    rec_path = INTERIM / "epc_recommendations.parquet"
    labels = None
    if rec_path.exists():
        rec = pd.read_parquet(rec_path)
        labels, old_boiler_certs = build_labels(rec)
        gas_boiler = df["heating_system"].isin(["gas_boiler_condensing", "gas_boiler_old"])
        old = df["CERT_ID"].isin(set(old_boiler_certs))
        df.loc[gas_boiler & old, "heating_system"] = "gas_boiler_old"
        print(
            f"gas boilers marked old from assessor recommendation 20: {int((gas_boiler & old).sum()):,} "
            f"of {int(gas_boiler.sum()):,}"
        )
    else:
        print("WARNING: no recommendations -> condensing status from MAINHEAT_ENERGY_EFF only")
    df["region"] = df["LOCAL_AUTHORITY"].map(REGIONS["local_authority_to_region"])
    df["bedrooms"] = estimate_bedrooms(df)
    df["gas_connected"] = df["MAINS_GAS_FLAG"].str.upper().eq("Y") | df["main_fuel"].eq("mains_gas")
    df["outdoor_space"] = np.where(
        df["property_type"].isin(["detached", "semi_detached", "terraced", "bungalow"]), "yes", None
    )
    df["listed_or_conservation"] = None  # not in EPC; stays unknown (feasibility -> needs_survey)
    df["property_key"] = property_keys(df)

    # deterministic ids, in hash order (no address/date ordering leaks into ids)
    keys = pd.Series(df["property_key"].unique())
    keys = keys.iloc[np.argsort(keys.map(_md5).to_numpy())]
    # real properties start at P200001; P10001-P19999 are reserved for synthetic demo homes
    # (e.g. the PS2 example home P10001)
    pid = pd.Series([f"P{200001 + i}" for i in range(len(keys))], index=keys.to_numpy())
    df["property_id"] = df["property_key"].map(pid)
    df["cert_id"] = df["CERT_ID"].astype(str).map(lambda s: _md5("cert|" + s)[:16])

    df = df.sort_values(["property_id", "lodgement_date", "cert_id"]).reset_index(drop=True)
    df.to_parquet(INTERIM / "epc_certs_parsed.parquet", index=False)

    model_cols = [
        "cert_id",
        "property_id",
        "lodgement_date",
        "LOCAL_AUTHORITY",
        "region",
        "floor_area_m2",
        "habitable_rooms",
        "bedrooms",
        "gas_connected",
        "energy_rating",
        "sap_score",
        "TRANSACTION_TYPE",
        "TENURE",
        "FLOOR_LEVEL",
        "FLAT_TOP_STOREY",
    ] + ENUM_COLS
    model = df[model_cols].rename(
        columns={
            "LOCAL_AUTHORITY": "local_authority_code",
            "TRANSACTION_TYPE": "transaction_type",
            "TENURE": "tenure",
            "FLOOR_LEVEL": "floor_level",
            "FLAT_TOP_STOREY": "flat_top_storey",
        }
    )
    assert not set(LEAKY) & set(model.columns)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    model.to_parquet(PROCESSED / "epc_certificates_model.parquet", index=False)

    if labels is not None:
        # recommender labels (BUILD_GUIDE P3.3): one row per certificate x retrofit
        feas = feasible_set(
            df.set_index("CERT_ID")[
                [
                    "property_type",
                    "roof_type",
                    "roof_insulation",
                    "wall_type",
                    "wall_insulation",
                    "glazing",
                    "smart_controls",
                    "heating_system",
                    "renewables",
                ]
            ]
        )
        long = feas.stack().rename("rule_feasible").reset_index().rename(columns={"level_1": "retrofit"})
        long = long.merge(labels, on=["CERT_ID", "retrofit"], how="left")
        long["assessor_recommended"] = long["assessor_order"].notna()
        long["assessor_order"] = long["assessor_order"].astype("Int64")
        ids = df[["CERT_ID", "cert_id", "property_id"]]
        long = long.merge(ids, on="CERT_ID").drop(columns=["CERT_ID", "indicative_cost"])
        (PROCESSED / "labels").mkdir(parents=True, exist_ok=True)
        # rows that are neither rule-feasible nor recommended carry no label information (and would
        # push the file over GitHub's 100 MB limit); rates above were computed on the full table
        long = long[long["rule_feasible"] | long["assessor_recommended"]]
        long[
            ["cert_id", "property_id", "retrofit", "rule_feasible", "assessor_recommended", "assessor_order"]
        ].to_parquet(PROCESSED / "labels" / "recommender_labels.parquet", index=False)
        rates = long.groupby("retrofit").agg(
            feasible=("rule_feasible", "mean"), recommended=("assessor_recommended", "mean")
        )
        rates["recommended_given_feasible"] = (
            long[long.rule_feasible].groupby("retrofit")["assessor_recommended"].mean()
        )
        rates["recommended_when_rule_infeasible"] = (
            long[~long.rule_feasible].groupby("retrofit")["assessor_recommended"].mean()
        )
        rates.round(4).to_csv(REPORTS / "recommender_label_rates.csv")
        print("recommender label rates:\n", rates.round(3).to_string())

    latest = df.groupby("property_id", sort=False).tail(1)
    scope = (
        latest["main_fuel"].isin(["mains_gas", "electricity"])
        & latest["heating_system"].notna()
        & latest["heating_system"].ne("other_fuel_boiler")
        & latest["property_type"].notna()
        & latest["age_band"].notna()
        & latest["region"].notna()
    )
    drop_counts["latest_out_of_scope"] = int((~scope).sum())
    latest[scope].to_parquet(INTERIM / "properties_latest.parquet", index=False)
    print(
        f"certificates: {n0:,} raw -> {len(df):,} valid; properties: {latest['property_id'].nunique():,}; "
        f"in scope: {int(scope.sum()):,}"
    )
    print("dropped:", drop_counts)
    pd.Series(drop_counts).to_csv(REPORTS / "epc_drop_counts.csv")


if __name__ == "__main__":
    main()
