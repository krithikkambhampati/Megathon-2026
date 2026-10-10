"""EPC bulk download(s) -> interim parquet (certificates + recommendations) for target LAs.

Tolerant of how the files were obtained:
  * any number of .zip and/or .csv files under data/raw/epc/ (per-LA or national, any year split)
  * column names normalised to UPPER_SNAKE (old bulk files, new service, API-style hyphens)
  * certificate id: CERTIFICATE_NUMBER (service since Mar 2026) or LMK_KEY (older files)
Certificate files are recognised by having CURRENT_ENERGY_RATING; recommendation files by
IMPROVEMENT_ITEM. Rows outside config target_local_authorities are dropped while scanning.

Outputs (git-ignored, contain addresses):
  data/interim/epc_certificates.parquet
  data/interim/epc_recommendations.parquet
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "epc"
EXTRACT = ROOT / "data" / "interim" / "epc_extracted"
OUT_CERT = ROOT / "data" / "interim" / "epc_certificates.parquet"
OUT_REC = ROOT / "data" / "interim" / "epc_recommendations.parquet"
CFG = yaml.safe_load((ROOT / "config" / "data_pipeline.yaml").read_text())
TARGET_LAS = set(CFG["target_local_authorities"])

CERT_COLS = [
    "CERT_ID",
    "UPRN",
    "ADDRESS1",
    "ADDRESS2",
    "ADDRESS3",
    "ADDRESS",
    "POSTCODE",
    "LOCAL_AUTHORITY",
    "LODGEMENT_DATE",
    "INSPECTION_DATE",
    "TRANSACTION_TYPE",
    "TENURE",
    "CURRENT_ENERGY_RATING",
    "CURRENT_ENERGY_EFFICIENCY",
    "POTENTIAL_ENERGY_RATING",
    "POTENTIAL_ENERGY_EFFICIENCY",
    "PROPERTY_TYPE",
    "BUILT_FORM",
    "CONSTRUCTION_AGE_BAND",
    "TOTAL_FLOOR_AREA",
    "NUMBER_HABITABLE_ROOMS",
    "NUMBER_HEATED_ROOMS",
    "MAIN_FUEL",
    "MAINS_GAS_FLAG",
    "MAINHEAT_DESCRIPTION",
    "MAINHEAT_ENERGY_EFF",
    "MAINHEATCONT_DESCRIPTION",
    "MAINHEATC_ENERGY_EFF",
    "SECONDHEAT_DESCRIPTION",
    "WALLS_DESCRIPTION",
    "WALLS_ENERGY_EFF",
    "ROOF_DESCRIPTION",
    "ROOF_ENERGY_EFF",
    "WINDOWS_DESCRIPTION",
    "WINDOWS_ENERGY_EFF",
    "GLAZED_TYPE",
    "MULTI_GLAZE_PROPORTION",
    "HOTWATER_DESCRIPTION",
    "FLOOR_DESCRIPTION",
    "LIGHTING_DESCRIPTION",
    "PHOTO_SUPPLY",
    "SOLAR_WATER_HEATING_FLAG",
    "WIND_TURBINE_COUNT",
    "FLOOR_LEVEL",
    "FLAT_TOP_STOREY",
    "FLAT_STOREY_COUNT",
    "ENERGY_TARIFF",
    "MECHANICAL_VENTILATION",
    "REPORT_TYPE",
    # SAP-derived outputs: kept in interim ONLY for the data report; never model features (leakage)
    "ENERGY_CONSUMPTION_CURRENT",
    "CO2_EMISSIONS_CURRENT",
    "HEATING_COST_CURRENT",
    "HOT_WATER_COST_CURRENT",
    "LIGHTING_COST_CURRENT",
]
# the long IMPROVEMENT_DESCR_TEXT paragraph is not needed (summary text + id identify the measure)
REC_COLS = ["CERT_ID", "IMPROVEMENT_ITEM", "IMPROVEMENT_ID", "IMPROVEMENT_SUMMARY_TEXT", "INDICATIVE_COST"]


def norm_col(c: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", c.strip().upper()).strip("_")


def iter_csv_files(only: str | None = None):
    """Yield (name, path, cleanup) for every CSV: plain CSVs in place, zip members one at a time.

    Zip members are unpacked to a temp file, filtered, then deleted, so disk use stays bounded by
    the largest single member (the national zip is ~8 GB compressed, ~30+ GB unpacked).
    """

    def wanted(name: str) -> bool:
        n = name.lower()
        k = "rec" if "recommendation" in n else "cert"
        return only is None or k == only

    for p in sorted(RAW.rglob("*.csv")):
        if wanted(p.name):
            yield p.name, p, False
    EXTRACT.mkdir(parents=True, exist_ok=True)
    for z in sorted(RAW.rglob("*.zip")):
        with zipfile.ZipFile(z) as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".csv") or not wanted(name):
                    continue
                tag = hashlib.md5(f"{z.name}/{name}".encode()).hexdigest()[:8]
                dest = EXTRACT / f"{Path(name).stem}__{tag}.csv"
                with zf.open(name) as src, dest.open("wb") as dst:
                    while chunk := src.read(1 << 22):
                        dst.write(chunk)
                yield f"{z.name}:{name}", dest, True


def scan(path: Path) -> pl.LazyFrame:
    lf = pl.scan_csv(
        path, infer_schema_length=0, encoding="utf8-lossy", ignore_errors=True, truncate_ragged_lines=True
    )
    names = lf.collect_schema().names()
    lf = lf.rename({c: norm_col(c) for c in names})
    cols = [norm_col(c) for c in names]
    if "CERTIFICATE_NUMBER" in cols:
        lf = lf.rename({"CERTIFICATE_NUMBER": "CERT_ID"})
    elif "LMK_KEY" in cols:
        lf = lf.rename({"LMK_KEY": "CERT_ID"})
    return lf


def select_cols(lf: pl.LazyFrame, wanted: list[str]) -> pl.LazyFrame:
    have = set(lf.collect_schema().names())
    return lf.select([pl.col(c) if c in have else pl.lit(None, dtype=pl.String).alias(c) for c in wanted])


def main() -> None:
    """Two passes: certificates first (filtered to target LAs), then recommendations filtered to
    those certificate ids. Each pass streams one CSV at a time, so memory and disk stay bounded
    (the national zip is ~98 GB uncompressed; single recommendation files reach ~7 GB)."""
    CHUNKS = ROOT / "data" / "interim" / "epc_chunks"
    CHUNKS.mkdir(parents=True, exist_ok=True)

    def kind(name: str) -> str:
        n = name.lower()
        return "rec" if "recommendation" in n else "cert" if "certificate" in n else "other"

    # pass 1: certificates
    n_cert = 0
    for k, (name, path, cleanup) in enumerate(iter_csv_files(only="cert")):
        lf = scan(path)
        if "CURRENT_ENERGY_RATING" not in set(lf.collect_schema().names()):
            print(f"ignored (not a certificate file): {name}")
        else:
            out = CHUNKS / f"cert_{k:04d}.parquet"
            select_cols(lf, CERT_COLS).filter(pl.col("LOCAL_AUTHORITY").is_in(TARGET_LAS)).sink_parquet(out)
            n_cert += 1
            print(
                f"cert {name}: {pl.scan_parquet(out).select(pl.len()).collect().item():,} rows in target LAs"
            )
        if cleanup:
            path.unlink()
    if not n_cert:
        raise SystemExit(f"No EPC certificate files found under {RAW}. See data_pipeline/download/README.md")
    cert = pl.read_parquet(CHUNKS / "cert_*.parquet").unique(subset="CERT_ID", keep="last")
    print(f"certificates in target LAs: {len(cert):,}")
    print(cert.group_by("LOCAL_AUTHORITY").len().sort("LOCAL_AUTHORITY"))
    cert.write_parquet(OUT_CERT)
    ids = cert.select("CERT_ID").lazy()

    # pass 2: recommendations for those certificates only
    n_rec = 0
    for k, (name, path, cleanup) in enumerate(iter_csv_files(only="rec")):
        lf = scan(path)
        if "IMPROVEMENT_ITEM" in set(lf.collect_schema().names()):
            out = CHUNKS / f"rec_{k:04d}.parquet"
            select_cols(lf, REC_COLS).join(ids, on="CERT_ID", how="semi").sink_parquet(out)
            n_rec += 1
            print(f"rec  {name}: {pl.scan_parquet(out).select(pl.len()).collect().item():,} rows kept")
        if cleanup:
            path.unlink()
    if n_rec:
        rec = pl.read_parquet(CHUNKS / "rec_*.parquet").unique()
        rec.write_parquet(OUT_REC)
        print(f"recommendations for target certificates: {len(rec):,}")
    else:
        print("WARNING: no recommendations file found; the recommender labels (README P3.3) need it")
    for f in CHUNKS.iterdir():
        f.unlink()
    CHUNKS.rmdir()


if __name__ == "__main__":
    main()
