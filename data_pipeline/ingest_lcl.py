"""Low Carbon London smart meter trial -> monthly electricity profile + household dispersion.

Uses standard-tariff ("Std") households only (the dToU group had price-driven behaviour in 2013),
calendar year 2013 (the only complete year), and only household-months with >= 95% of
half-hour readings present (missing readings are never treated as zero).

Outputs (data/processed/reference/, aggregated, CC BY UK Power Networks):
  lcl_monthly_profile.parquet   month_num, share (median household share, renormalised), n_households
  lcl_household_annual.parquet  annual kWh per complete household (anonymous; used for dispersion stats)
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "raw" / "lcl" / "Partitioned_LCL_Data.zip"
OUT = ROOT / "data" / "processed" / "reference"
YEAR = 2013
MIN_COVERAGE = 0.95


def monthly_from_member(raw: bytes) -> pl.DataFrame:
    df = pl.read_csv(io.BytesIO(raw), infer_schema_length=0)
    df = df.rename({c: c.strip() for c in df.columns})
    kwh_col = next(c for c in df.columns if c.upper().startswith("KWH"))
    return (
        df.filter(pl.col("stdorToU") == "Std")
        .with_columns(
            pl.col("DateTime")
            .str.slice(0, 19)
            .str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False)
            .alias("ts"),
            pl.col(kwh_col).str.strip_chars().cast(pl.Float64, strict=False).alias("kwh"),
        )
        .filter(pl.col("ts").dt.year() == YEAR)
        .group_by("LCLid", pl.col("ts").dt.month().alias("month_num"))
        .agg(pl.col("kwh").sum(), pl.col("kwh").is_not_null().sum().alias("n_readings"))
    )


def main() -> None:
    parts = []
    with zipfile.ZipFile(SRC) as zf:
        members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
        for i, m in enumerate(members, 1):
            parts.append(monthly_from_member(zf.read(m)))
            if i % 20 == 0:
                print(f"{i}/{len(members)} files")
    # a household can span two partition files -> re-aggregate
    hm = pl.concat(parts).group_by("LCLid", "month_num").agg(pl.col("kwh").sum(), pl.col("n_readings").sum())
    days = pl.Series([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
    hm = hm.with_columns(
        (
            pl.col("n_readings")
            / (pl.col("month_num").map_elements(lambda m: days[m - 1], return_dtype=pl.Int64) * 48)
        ).alias("coverage")
    )
    good = hm.filter(pl.col("coverage") >= MIN_COVERAGE)
    complete = (
        good.group_by("LCLid")
        .agg(pl.len().alias("n_months"), pl.col("kwh").sum().alias("annual_kwh"))
        .filter(pl.col("n_months") == 12)
    )
    good = good.join(complete.select("LCLid", "annual_kwh"), on="LCLid")
    shares = (
        good.with_columns((pl.col("kwh") / pl.col("annual_kwh")).alias("share"))
        .group_by("month_num")
        .agg(pl.col("share").median(), pl.len().alias("n_households"))
        .sort("month_num")
    )
    shares = shares.with_columns(pl.col("share") / pl.col("share").sum())
    OUT.mkdir(parents=True, exist_ok=True)
    shares.write_parquet(OUT / "lcl_monthly_profile.parquet")
    complete.select("annual_kwh").write_parquet(OUT / "lcl_household_annual.parquet")
    a = complete["annual_kwh"]
    print(shares)
    print(
        f"complete Std households: {len(complete):,}; annual kWh median {a.median():.0f}, "
        f"IQR {a.quantile(0.25):.0f}-{a.quantile(0.75):.0f}"
    )


if __name__ == "__main__":
    main()
