"""HM Land Registry Price Paid Data -> cleaned interim parquet (England & Wales, all years configured).

Keeps standard residential transactions only: ppd_category 'A' (standard price paid, excludes
repossessions/buy-to-let portfolio/transfers to companies) and property_type in D/S/T/F
('O' = other is excluded). Record status 'A' (added); later C/D (change/delete) records only
appear in the monthly update files, not in the yearly files we use.

Output: data/interim/ppd_clean.parquet (contains addresses -> never committed)
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "ppd"
OUT = ROOT / "data" / "interim" / "ppd_clean.parquet"
CFG = yaml.safe_load((ROOT / "config" / "data_pipeline.yaml").read_text())

COLS = [
    "transaction_id",
    "price_gbp",
    "date_of_transfer",
    "postcode",
    "ppd_property_type",
    "old_new",
    "duration",
    "paon",
    "saon",
    "street",
    "locality",
    "town_city",
    "district",
    "county",
    "ppd_category",
    "record_status",
]


def norm_text(col: str) -> pl.Expr:
    """Uppercase, punctuation -> space, collapse whitespace (shared address normalisation)."""
    return (
        pl.col(col)
        .fill_null("")
        .str.to_uppercase()
        .str.replace_all(r"[^A-Z0-9 ]", " ")
        .str.replace_all(r"\s+", " ")
        .str.strip_chars()
    )


def main() -> None:
    # lazy scan + streaming sink keeps peak memory low (~11M rows across the yearly files)
    files = [RAW / f"pp-{y}.csv" for y in CFG["ppd_years"]]
    df = pl.concat([pl.scan_csv(f, has_header=False, new_columns=COLS, infer_schema_length=0) for f in files])
    n0 = df.select(pl.len()).collect().item()
    df = (
        df.filter(
            (pl.col("ppd_category") == "A")
            & (pl.col("record_status") == "A")
            & pl.col("ppd_property_type").is_in(["D", "S", "T", "F"])
        )
        .with_columns(
            pl.col("price_gbp").cast(pl.Int64),
            pl.col("date_of_transfer").str.slice(0, 10).str.strptime(pl.Date, "%Y-%m-%d"),
            pl.col("postcode").str.to_uppercase().str.replace_all(r"\s+", " ").str.strip_chars(),
            (pl.col("old_new") == "Y").alias("new_build"),
            pl.col("duration").replace({"F": "freehold", "L": "leasehold"}).alias("tenure"),
            norm_text("paon").alias("paon_norm"),
            norm_text("saon").alias("saon_norm"),
            norm_text("street").alias("street_norm"),
        )
        .filter(pl.col("postcode").str.contains(r"^[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}$"))
        .filter((pl.col("price_gbp") >= 10_000) & (pl.col("price_gbp") <= 20_000_000))
        .drop(["old_new", "duration", "record_status", "ppd_category"])
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.sink_parquet(OUT)
    n1 = pl.scan_parquet(OUT).select(pl.len()).collect().item()
    print(f"kept {n1:,} of {n0:,} transactions")


if __name__ == "__main__":
    main()
