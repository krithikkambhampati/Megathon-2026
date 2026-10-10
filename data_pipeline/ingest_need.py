"""Parse DESNZ NEED consumption tables (2026 release, data years to 2024) into tidy tables.

Outputs (data/processed/reference/, committed: aggregated public statistics, OGL v3):
  need_headline.parquet   one row per (source_table, fuel, metric, dimension, category, year)
  need_multi.parquet      multiple-attributes table (region x type x age x bedrooms x gas x tariff)
                          with mean / quartiles per fuel, mapped to our enums where possible

NEED sheets hold several sub-tables side by side (a: counts, b: mean, c: median ...),
separated by an empty column. Each sub-table starts with a header row whose first cell is "Year".
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "need"
OUT = ROOT / "data" / "processed" / "reference"

# headline tables we use, with the dimension they break down by
HEADLINE = {
    "Consumption_headline_EW_2024.xlsx": {
        "Table_1": ("gas", "floor_area_band"), "Table_2": ("electricity", "floor_area_band"),
        "Table_3": ("gas", "bedrooms"), "Table_4": ("electricity", "bedrooms"),
        "Table_5": ("gas", "property_type"), "Table_6": ("electricity", "property_type"),
        "Table_7": ("gas", "property_age"), "Table_8": ("electricity", "property_age"),
        "Table_15": ("gas", "region"), "Table_16": ("electricity", "region"),
        "Table_27": ("gas", "epc_band"), "Table_28": ("electricity", "epc_band"),
    },
    "Consumption_gas_per_square_metre_EW_2024.xlsx": {
        "Table_1.2": ("gas_per_m2", "floor_area_band"), "Table_3.2": ("gas_per_m2", "property_type"),
        "Table_4.2": ("gas_per_m2", "property_age"), "Table_8.2": ("gas_per_m2", "region"),
        "Table_14.2": ("gas_per_m2", "epc_band"),
    },
}

METRIC_PATTERNS = [
    (r"number of dwellings", "count"),
    (r"lower quartile", "q25"),
    (r"upper quartile", "q75"),
    (r"median", "median"),
    (r"mean", "mean"),
]


def _metric(title: str) -> str | None:
    t = title.lower()
    for pat, name in METRIC_PATTERNS:
        if re.search(pat, t):
            return name
    return None


def _num(v):
    if isinstance(v, str):
        return np.nan  # "[no data]", "[c]" (suppressed) etc.
    return float(v) if pd.notna(v) else np.nan


def parse_sheet(df: pd.DataFrame) -> list[dict]:
    """Return long rows from every side-by-side sub-table in a NEED sheet."""
    rows: list[dict] = []
    header_rows = [i for i in range(len(df)) if str(df.iat[i, 0]).strip() == "Year"]
    for h in header_rows:
        cols = df.columns
        c = 0
        while c < len(cols):
            if str(df.iat[h, c]).strip() != "Year":
                c += 1
                continue
            # sub-table spans from c until the next empty header cell
            end = c + 1
            while end < len(cols) and pd.notna(df.iat[h, end]) and str(df.iat[h, end]).strip() != "Year":
                end += 1
            title = str(df.iat[h - 1, c]) if h > 0 else ""
            metric = _metric(title)
            categories = [str(df.iat[h, k]).strip() for k in range(c + 1, end)]
            r = h + 1
            while r < len(df) and pd.notna(df.iat[r, c]) and str(df.iat[r, c]).strip() not in ("", "Year"):
                year = df.iat[r, c]
                try:
                    year = int(year)
                except (TypeError, ValueError):
                    break
                for k, cat in zip(range(c + 1, end), categories):
                    rows.append({"metric": metric, "metric_title": title, "category": cat,
                                 "year": year, "value": _num(df.iat[r, k])})
                r += 1
            c = end
    return rows


def build_headline() -> pd.DataFrame:
    out = []
    for fname, tables in HEADLINE.items():
        book = pd.read_excel(RAW / fname, sheet_name=list(tables), header=None)
        for sheet, (fuel, dim) in tables.items():
            for row in parse_sheet(book[sheet]):
                out.append({"source": f"{fname}:{sheet}", "fuel": fuel, "dimension": dim, **row})
    df = pd.DataFrame(out)
    assert df["metric"].notna().all(), "unrecognised NEED sub-table title"
    return df


# ---- multiple attributes table -> our enums -------------------------------------------------

REGION_MAP = {
    "North East": "north_east", "North West": "north_west",
    "Yorkshire and The Humber": "yorkshire_humber", "East Midlands": "east_midlands",
    "West Midlands": "west_midlands", "East of England": "east_of_england", "East": "east_of_england",
    "London": "london", "South East": "south_east", "South West": "south_west", "Wales": "wales",
}
# NEED property types -> ours. NEED has no bungalow/maisonette split in this table; documented.
PTYPE_MAP = {"Detached": "detached", "Semi detached": "semi_detached", "Semi-detached": "semi_detached",
             "End terrace": "terraced", "Mid terrace": "terraced", "Bungalow": "bungalow",
             "Converted flat": "flat", "Purpose built flat": "flat", "Flat": "flat"}


def build_multi() -> pd.DataFrame:
    t = pd.read_excel(RAW / "Consumption_multiple_attributes_EW_2024.xlsx", sheet_name="Table", header=None)
    hdr = next(i for i in range(len(t)) if str(t.iat[i, 0]).strip() == "Year")
    df = t.iloc[hdr + 1:].copy()
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in t.iloc[hdr]]
    df = df.rename(columns={
        "Year": "year", "Region code": "region_code", "Region": "need_region",
        "Property type": "need_property_type", "Property age": "need_property_age",
        "Number of bedrooms": "need_bedrooms", "Gas present": "gas_present",
        "Electricity type": "electricity_type", "Number in sample": "n",
        "Mean: Gas": "gas_mean", "Lower quartile: Gas": "gas_q25", "Median: Gas": "gas_median",
        "Upper quartile: Gas": "gas_q75", "Mean: Electricity": "elec_mean",
        "Lower quartile: Electricity": "elec_q25", "Median: Electricity": "elec_median",
        "Upper quartile: Electricity": "elec_q75",
    })
    for c in ["n", "gas_mean", "gas_q25", "gas_median", "gas_q75",
              "elec_mean", "elec_q25", "elec_median", "elec_q75"]:
        df[c] = df[c].map(_num)
    df["year"] = df["year"].astype(int)
    df["region"] = df["need_region"].map(REGION_MAP)
    df["property_type"] = df["need_property_type"].map(PTYPE_MAP)
    df["bedrooms_n"] = df["need_bedrooms"].astype(str).str.extract(r"(\d+)")[0].astype("Int64")
    df["gas_present"] = df["gas_present"].astype(str).str.strip().eq("Yes")
    return df.reset_index(drop=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    head = build_headline()
    head.to_parquet(OUT / "need_headline.parquet", index=False)
    multi = build_multi()
    multi.to_parquet(OUT / "need_multi.parquet", index=False)
    print(f"need_headline: {len(head)} rows; need_multi: {len(multi)} rows")
    print("unmapped NEED property types:", sorted(multi.loc[multi.property_type.isna(), "need_property_type"].unique()))
    print("unmapped NEED regions:", sorted(multi.loc[multi.region.isna(), "need_region"].unique()))
    print("NEED ages:", sorted(multi["need_property_age"].astype(str).unique()))


if __name__ == "__main__":
    main()
