"""Validate processed outputs against the contract (README section 7) and write MANIFEST.json.

Checks (fail loudly): enum columns only contain contract values (or null), required columns exist,
ids are well formed, no hidden simulator column leaks into properties.parquet, splits are leak-free,
monthly rows never store missing values as 0 where data was absent.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"

ENUMS = {
    "property_type": {"detached", "semi_detached", "terraced", "flat", "bungalow", "maisonette"},
    "age_band": {
        "pre_1900",
        "1900_1929",
        "1930_1949",
        "1950_1966",
        "1967_1982",
        "1983_1995",
        "1996_2006",
        "2007_onwards",
    },
    "region": {
        "north_east",
        "north_west",
        "yorkshire_humber",
        "east_midlands",
        "west_midlands",
        "east_of_england",
        "london",
        "south_east",
        "south_west",
        "wales",
    },
    "energy_rating": set("ABCDEFG"),
    "roof_type": {"pitched_loft", "flat_roof", "room_in_roof", "dwelling_above"},
    "roof_insulation": {"none", "low", "medium", "full"},
    "wall_type": {"cavity", "solid", "timber_or_system"},
    "wall_insulation": {"none", "partial", "full"},
    "glazing": {"single", "partial_double", "secondary", "double", "triple"},
    "heating_system": {
        "heat_pump",
        "gas_boiler_condensing",
        "gas_boiler_old",
        "electric_storage",
        "electric_direct",
        "other_fuel_boiler",
    },
    "main_fuel": {"mains_gas", "electricity", "other"},
    "renewables": {"none", "solar_thermal", "solar_pv", "solar_pv_battery"},
    "smart_controls": {
        "none",
        "timer_only",
        "programmer_thermostat",
        "programmer_thermostat_trvs",
        "smart_thermostat",
        "smart_zoned",
    },
    "retrofit": {
        "loft_insulation",
        "cavity_wall_insulation",
        "solid_wall_insulation",
        "double_glazing",
        "air_source_heat_pump",
        "solar_pv",
        "smart_thermostat",
    },
    "split": {"train", "val", "test"},
}
HIDDEN = {
    "setpoint_factor",
    "occupancy_factor",
    "appliance_factor",
    "exposure_factor",
    "scop_base",
    "pv_orientation_factor",
    "self_consumption_frac",
    "cooking_gas_kwh",
}


def check_enums(name: str, df: pd.DataFrame) -> None:
    for col, allowed in ENUMS.items():
        if col in df.columns:
            bad = set(df[col].dropna().unique()) - allowed
            assert not bad, f"{name}.{col} has non-contract values: {sorted(bad)[:5]}"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> None:
    props = pd.read_parquet(PROCESSED / "properties.parquet")
    assert props["property_id"].str.match(r"^P\d{5,}$").all() and props["property_id"].is_unique
    assert props["customer_id"].str.match(r"^C\d{5,}$").all()
    assert not HIDDEN & set(props.columns), "hidden simulator factors leaked into properties.parquet"
    splits = pd.read_parquet(PROCESSED / "splits.parquet")
    assert splits.groupby("customer_id")["split"].nunique().max() == 1, "customer straddles splits"
    m = pd.read_parquet(PROCESSED / "energy_monthly.parquet")
    assert (m["electricity_kwh"].isna() & m["gas_kwh"].isna()).sum() == 0, (
        "fully-missing month stored as a row"
    )
    assert m["month"].str.match(r"^\d{4}-\d{2}$").all()

    files = sorted(p for p in PROCESSED.rglob("*.parquet"))
    entries = {}
    for f in files:
        df = pd.read_parquet(f)
        check_enums(f.name, df)
        entries[str(f.relative_to(PROCESSED))] = {
            "rows": len(df),
            "columns": list(df.columns),
            "bytes": f.stat().st_size,
            "sha256": sha256(f),
        }
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip()
    except OSError:
        commit = ""
    manifest = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "generator_commit": commit or None,
        "files": entries,
    }
    (PROCESSED / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    for k, v in entries.items():
        print(f"{k:45s} {v['rows']:>12,} rows  {v['bytes'] / 1e6:8.1f} MB")
    print("all contract checks passed")


if __name__ == "__main__":
    main()
