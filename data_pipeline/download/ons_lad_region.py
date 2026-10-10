"""Build a local-authority-code -> region lookup from the ONS Open Geography Portal (OGL v3).

EPC certificates span 2012-2026, and local authority codes changed during that period
(e.g. the 2019-2023 unitary mergers). So we union every LADyy -> RGNyy England lookup
from 2015 to 2025. Every Welsh code (W06*) maps to 'wales'.

Output: data/processed/reference/lad_region_lookup.csv  (lad_code, lad_name, region, ons_year)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "processed" / "reference" / "lad_region_lookup.csv"
BASE = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"

ENGLAND = {
    15: "LAD15_RGN15_EN_LU_a7a2e5e44b314dc39f1573917ab3db64",
    16: "LAD16_RGN16_EN_LU_4c75a5a2d1e14f24a0efcc7eefe66db3",
    17: "LAD17_RGN17_EN_LU_c5e0d2988ca24f54ae16cceb6f101f19",
    18: "LAD18_RGN18_EN_LU_2789dae82efa497d98e12a0ce1d5586f",
    19: "LAD19_RGN19_EN_LU_948748b0eaa54fe888a604b126f5e672",
    20: "LAD20_RGN20_EN_LU_ac320f89513b454ca1ccdb00300ffd38",
    21: "LAD21_RGN21_EN_LU_e39114ca0d934551b012bba304cdd11f",
    22: "LAD22_RGN22_EN_LU",
    23: "LAD23_RGN23_EN_LU",
    24: "LAD24_RGN24_EN_LU",
    25: "LAD25_RGN25_EN_LU_v2",
}
WALES_SERVICE = "WD25_LAD25_CTYUA25_RGN25_CTRY25_UK_LU"

REGION_NAME_TO_ENUM = {
    "North East": "north_east",
    "North West": "north_west",
    "Yorkshire and The Humber": "yorkshire_humber",
    "East Midlands": "east_midlands",
    "West Midlands": "west_midlands",
    "East of England": "east_of_england",
    "London": "london",
    "South East": "south_east",
    "South West": "south_west",
}


def query_all(service: str) -> list[dict]:
    rows, offset = [], 0
    while True:
        r = requests.get(
            f"{BASE}/{service}/FeatureServer/0/query",
            timeout=60,
            params={
                "where": "1=1",
                "outFields": "*",
                "f": "json",
                "resultOffset": offset,
                "resultRecordCount": 2000,
            },
        )
        r.raise_for_status()
        body = r.json()
        feats = body.get("features", [])
        rows += [f["attributes"] for f in feats]
        # the server caps page size below what we ask for, so page until it says no more
        if not feats or not body.get("exceededTransferLimit"):
            return rows
        offset += len(feats)


def pick(attrs: dict, prefix: str) -> str:
    key = next(k for k in attrs if k.upper().startswith(prefix))
    return attrs[key]


def main() -> None:
    out = []
    for yy, svc in ENGLAND.items():
        for a in query_all(svc):
            out.append(
                {
                    "lad_code": pick(a, f"LAD{yy}CD"),
                    "lad_name": pick(a, f"LAD{yy}NM"),
                    "region": REGION_NAME_TO_ENUM[pick(a, f"RGN{yy}NM")],
                    "ons_year": 2000 + yy,
                }
            )
    for a in query_all(WALES_SERVICE):
        code = pick(a, "LAD25CD")
        if code.startswith("W06"):
            out.append(
                {"lad_code": code, "lad_name": pick(a, "LAD25NM"), "region": "wales", "ons_year": 2025}
            )
    df = (
        pd.DataFrame(out)
        .sort_values("ons_year", ascending=False)
        .drop_duplicates("lad_code")
        .sort_values("lad_code")
    )
    # a code must never map to two regions across years
    assert df["lad_code"].is_unique
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"{len(df)} LAD codes -> {df.region.nunique()} regions")
    print(df.region.value_counts())


if __name__ == "__main__":
    main()
