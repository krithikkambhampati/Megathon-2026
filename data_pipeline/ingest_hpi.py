"""UK House Price Index -> tidy monthly index per (area, property type).

Output: data/processed/reference/hpi_monthly.parquet
  area_code, area_name, month (YYYY-MM), ppd_property_type (D/S/T/F/ALL), index, average_price
Used to (a) re-index historic sale prices to as_of_month (current value baseline) and
(b) give the value model a market-conditions feature at the time of each sale.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "raw" / "hpi" / "UK-HPI-full-file-2026-07.csv"
OUT = ROOT / "data" / "processed" / "reference" / "hpi_monthly.parquet"

TYPE_COLS = {
    "ALL": ("Index", "AveragePrice"),
    "D": ("DetachedIndex", "DetachedPrice"),
    "S": ("SemiDetachedIndex", "SemiDetachedPrice"),
    "T": ("TerracedIndex", "TerracedPrice"),
    "F": ("FlatIndex", "FlatPrice"),
}


def main() -> None:
    raw = pl.read_csv(SRC, infer_schema_length=0)
    raw = raw.with_columns(
        pl.col("Date").str.strptime(pl.Date, "%d/%m/%Y").dt.strftime("%Y-%m").alias("month")
    )
    parts = []
    for t, (ic, pc) in TYPE_COLS.items():
        parts.append(
            raw.select(
                pl.col("AreaCode").alias("area_code"),
                pl.col("RegionName").alias("area_name"),
                "month",
                pl.lit(t).alias("ppd_property_type"),
                pl.col(ic).cast(pl.Float64, strict=False).alias("index"),
                pl.col(pc).cast(pl.Float64, strict=False).alias("average_price"),
            )
        )
    df = pl.concat(parts).filter(pl.col("index").is_not_null())
    df = df.filter(
        pl.col("area_code").str.slice(0, 1).is_in(["E", "W", "K"])
    )  # England, Wales, GB/UK aggregates
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.sort(["area_code", "ppd_property_type", "month"]).write_parquet(OUT)
    print(df.shape, df["month"].min(), "->", df["month"].max())


if __name__ == "__main__":
    main()
