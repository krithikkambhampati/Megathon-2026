"""Run the whole Part 1 pipeline in order (after raw downloads exist).

    python -m data_pipeline.run_all            # everything
    python -m data_pipeline.run_all --from build_dataset

Raw downloads: python -m data_pipeline.download.download_public, ...download.ons_lad_region,
and ...download.epc_bulk (needs EPC_API_TOKEN in .env). See data_pipeline/download/README.md.
"""
from __future__ import annotations

import argparse
import importlib
import time

STEPS = [
    "ingest_need",       # NEED tables -> reference parquet
    "ingest_ghg",        # DESNZ factors -> config/emission_factors.yaml
    "ingest_lcl",        # smart meter monthly profile
    "build_regions",     # config/regions.yaml
    "ingest_hpi",        # UK HPI tidy
    "ingest_ppd",        # Land Registry clean
    "ingest_epc",        # EPC certificates + recommendations for target LAs
    "build_properties",  # parse, ids, recommender labels, epc_certificates_model
    "join_epc_ppd",      # real sales history
    "repeat_epc",        # real retrofit history
    "build_dataset",     # sample, customers, splits, calibration, metering, simulator labels
    "value_baseline",    # current value -> properties.parquet
    "imputation_tables", # 'not sure' imputation tables for Part 2
    "make_examples",     # demo homes
    "manifest",          # MANIFEST.json + schema checks
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=STEPS[0], choices=STEPS)
    args = ap.parse_args()
    for step in STEPS[STEPS.index(args.start):]:
        t = time.time()
        print(f"\n=== {step} ===", flush=True)
        importlib.import_module(f"data_pipeline.{step}").main()
        print(f"=== {step} done in {time.time() - t:.0f}s ===", flush=True)


if __name__ == "__main__":
    main()
