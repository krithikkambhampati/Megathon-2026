"""Current value baseline (README P1.8) -> final data/processed/properties.parquet.

current_value_gbp is the property's estimated value at as_of_month. It is a baseline estimate, NOT
a sale price, and it is kept separate from sales_history (PS2 section 9):
  ppd_indexed  last real sale x HPI(LA, type, as_of) / HPI(LA, type, sale month)
  area_model   no sale: median indexed GBP/m2 of matched sales in the same LA x property type
               (from TRAIN-split properties only) x floor area
HPI type: flat/maisonette -> F, terraced -> T, semi_detached -> S, detached/bungalow -> D;
falls back to the LA all-types index when the type index is missing.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
PROCESSED = ROOT / "data" / "processed"
REF = PROCESSED / "reference"
REPORTS = ROOT / "reports"
CFG = yaml.safe_load((ROOT / "config" / "data_pipeline.yaml").read_text())
HPI_TYPE = {"flat": "F", "maisonette": "F", "terraced": "T", "semi_detached": "S",
            "detached": "D", "bungalow": "D"}


def hpi_lookup() -> pd.Series:
    h = pd.read_parquet(REF / "hpi_monthly.parquet")
    return h.set_index(["area_code", "ppd_property_type", "month"])["index"]


def index_factor(hpi: pd.Series, la: pd.Series, t: pd.Series, month: pd.Series, as_of: str) -> pd.Series:
    """HPI(as_of)/HPI(month) per row; type-specific with all-types fallback."""
    def get(code, typ, m):
        keys = list(zip(code, typ, m))
        return pd.Series(hpi.reindex(keys).to_numpy(), index=la.index)
    now_t, then_t = get(la, t, [as_of] * len(la)), get(la, t, month)
    now_a, then_a = get(la, ["ALL"] * len(la), [as_of] * len(la)), get(la, ["ALL"] * len(la), month)
    f = now_t / then_t
    return f.where(f.notna(), now_a / then_a)


def main() -> None:
    as_of = CFG["as_of_month"]
    hpi = hpi_lookup()
    props = pd.read_parquet(INTERIM / "properties_pre_value.parquet")
    sales = pd.read_parquet(PROCESSED / "sales_history.parquet")
    splits = pd.read_parquet(PROCESSED / "splits.parquet")
    certs = pd.read_parquet(PROCESSED / "epc_certificates_model.parquet",
                            columns=["property_id", "local_authority_code", "property_type", "floor_area_m2"])
    certs = certs.drop_duplicates("property_id", keep="last")

    # index every real sale to as_of
    s = sales.merge(certs, on="property_id", how="left")
    s["month"] = pd.to_datetime(s["sale_date"]).dt.strftime("%Y-%m")
    s["hpi_type"] = s["property_type"].map(HPI_TYPE)
    s["factor"] = index_factor(hpi, s["local_authority_code"], s["hpi_type"], s["month"], as_of)
    s["indexed_price"] = s["price_gbp"] * s["factor"]
    s["indexed_per_m2"] = s["indexed_price"] / s["floor_area_m2"]

    # area model from TRAIN properties' latest sale only (no leakage into val/test)
    last = s.sort_values("sale_date").groupby("property_id").tail(1)
    train = last[last["property_id"].isin(splits.loc[splits["split"] == "train", "property_id"])]
    per_m2 = train.groupby(["local_authority_code", "property_type"])["indexed_per_m2"].median()

    p = props.merge(last[["property_id", "indexed_price"]], on="property_id", how="left")
    model_val = p.set_index(["local_authority_code", "property_type"]).index.map(per_m2).to_numpy() \
        * p["floor_area_m2"].to_numpy()
    p["current_value_gbp"] = np.where(p["indexed_price"].notna(), p["indexed_price"], model_val).round(-2)
    p["current_value_source"] = np.where(p["indexed_price"].notna(), "ppd_indexed",
                                         np.where(np.isfinite(model_val), "area_model", None))
    p = p.drop(columns=["indexed_price"])
    PROCESSED.mkdir(parents=True, exist_ok=True)
    p.to_parquet(PROCESSED / "properties.parquet", index=False)

    rep = p.groupby("current_value_source", dropna=False)["current_value_gbp"].describe(percentiles=[.1, .5, .9])
    rep.to_csv(REPORTS / "current_value_summary.csv")
    print(rep.round(0).to_string())
    print("sales indexed with a valid HPI factor:", f"{s['factor'].notna().mean():.1%}")


if __name__ == "__main__":
    main()
