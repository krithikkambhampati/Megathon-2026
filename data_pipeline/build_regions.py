"""Build config/regions.yaml: per-region climate and seasonal profiles.

For each of our 10 regions:
  hdd_monthly         mean monthly heating degree days (base 15.5 C), 2016-2025, from Met Office
                      HadUK-Grid regional mean temperatures via Hitchin's formula
  hdd_factor          region annual HDD / England-and-Wales annual HDD (climate scaling of heat demand)
  gas_monthly_share   12 shares (sum 1): 75% space heating (proportional to HDD) + 25% hot water/cooking
                      (proportional to days x (55 C - mains water temp)); typical-gas-home split, documented
  elec_monthly_share  12 shares from the Low Carbon London smart meter trial (London households,
                      standard tariff, complete-year 2013); same shape used for every region (documented)
  pv_yield_kwh_per_kwp, pv_monthly_share   PVGIS v5.2, 35 deg, south, 14% loss, one town per region

Shares are used for seasonal annualisation of partial-year meter data and for synthetic monthly
profiles. Hitchin (1983): HDD_month = n * (Tb - T) / (1 - exp(-k (Tb - T))), k = 0.71 for the UK.
"""
from __future__ import annotations

import calendar
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
REF = ROOT / "data" / "processed" / "reference"
OUT = ROOT / "config" / "regions.yaml"

BASE_T = 15.5
HITCHIN_K = 0.71
YEARS = range(2016, 2026)
HEATING_SHARE_OF_GAS = 0.75  # typical gas home: ~75% space heating, ~25% hot water + cooking

# region -> (Met Office areal series, PVGIS town)
REGION_SERIES = {
    "north_east": ("England_E_and_NE", "Newcastle"),
    "north_west": ("England_NW_and_N_Wales", "Manchester"),
    "yorkshire_humber": ("England_E_and_NE", "Leeds"),
    "east_midlands": ("Midlands", "Nottingham"),
    "west_midlands": ("Midlands", "Birmingham"),
    "east_of_england": ("East_Anglia", "Norwich"),
    "london": ("England_SE_and_Central_S", "London"),
    "south_east": ("England_SE_and_Central_S", "Brighton"),
    "south_west": ("England_SW_and_S_Wales", "Bristol"),
    "wales": ("Wales", "Cardiff"),
}
MONTHS = [m.lower() for m in calendar.month_abbr[1:]]
DAYS = np.array([31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])


def read_metoffice(series: str) -> np.ndarray:
    """Mean monthly temperature (12 values) over YEARS."""
    path = RAW / "metoffice" / f"Tmean_{series}.txt"
    lines = path.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.split()[:2] == ["year", "jan"])
    df = pd.read_csv(path, sep=r"\s+", skiprows=start, na_values="---")
    df = df[df["year"].isin(YEARS)]
    assert len(df) == len(YEARS), f"{series}: missing years"
    return df[MONTHS].astype(float).mean().to_numpy()


def hitchin_hdd(t: np.ndarray) -> np.ndarray:
    d = BASE_T - t
    return DAYS * d / (1 - np.exp(-HITCHIN_K * d))


def mains_water_temp(t_air: np.ndarray) -> np.ndarray:
    # simple lagged-damped approximation of UK cold-mains temperature (range ~ 6-17 C)
    lagged = np.roll(t_air, 1)
    return 5.0 + 0.6 * lagged


def norm(x: np.ndarray) -> list[float]:
    x = np.asarray(x, dtype=float)
    return [round(float(v), 5) for v in x / x.sum()]


def elec_share() -> tuple[list[float], str]:
    p = REF / "lcl_monthly_profile.parquet"
    if p.exists():
        df = pd.read_parquet(p).sort_values("month_num")
        return norm(df["share"].to_numpy()), "Low Carbon London smart meter trial (UKPN), standard tariff, 2013"
    return norm(DAYS), "PLACEHOLDER: flat by days until data_pipeline/ingest_lcl.py has run"


def main() -> None:
    ew = hitchin_hdd(read_metoffice("England_and_Wales"))
    e_share, e_src = elec_share()
    regions = {}
    for region, (series, town) in REGION_SERIES.items():
        t = read_metoffice(series)
        hdd = hitchin_hdd(t)
        dhw = DAYS * (55.0 - mains_water_temp(t))
        gas = HEATING_SHARE_OF_GAS * hdd / hdd.sum() + (1 - HEATING_SHARE_OF_GAS) * dhw / dhw.sum()
        pv = json.loads((RAW / "pvgis" / f"pv_{region}.json").read_text())["outputs"]
        pv_m = np.array([m["E_m"] for m in pv["monthly"]["fixed"]])
        regions[region] = {
            "metoffice_series": series,
            "pvgis_town": town,
            "mean_temp_c": [round(float(v), 2) for v in t],
            "hdd_monthly": [round(float(v), 1) for v in hdd],
            "hdd_annual": round(float(hdd.sum()), 1),
            "hdd_factor": round(float(hdd.sum() / ew.sum()), 4),
            "gas_monthly_share": norm(gas),
            "elec_monthly_share": list(e_share),
            "pv_yield_kwh_per_kwp": round(float(pv["totals"]["fixed"]["E_y"]), 1),
            "pv_monthly_share": norm(pv_m),
        }
    national_gas = np.mean([regions[r]["gas_monthly_share"] for r in regions], axis=0)
    lad = pd.read_csv(REF / "lad_region_lookup.csv")
    doc = {
        "generated_by": "data_pipeline/build_regions.py (do not edit by hand)",
        "method": {
            "hdd": f"Hitchin formula, base {BASE_T} C, k={HITCHIN_K}, Met Office HadUK-Grid regional "
                   f"monthly mean temperature {YEARS.start}-{YEARS.stop - 1}",
            "gas_share": f"{HEATING_SHARE_OF_GAS:.0%} space heating x HDD + {1 - HEATING_SHARE_OF_GAS:.0%} "
                         "hot water/cooking x days x (55C - mains water temp)",
            "elec_share": e_src,
            "pv": "PVGIS v5.2 PVcalc, 1 kWp, 35 deg tilt, south, 14% system loss",
        },
        "national": {"hdd_annual": round(float(ew.sum()), 1), "gas_monthly_share": norm(national_gas),
                     "elec_monthly_share": list(e_share)},
        "regions": regions,
        "local_authority_to_region": dict(zip(lad["lad_code"], lad["region"])),
    }
    OUT.write_text("# Generated by data_pipeline/build_regions.py, do not edit by hand.\n"
                   "# Month lists are Jan..Dec.\n" + yaml.safe_dump(doc, sort_keys=False, width=200))
    for r, v in regions.items():
        print(f"{r:18s} HDD={v['hdd_annual']:7.1f} factor={v['hdd_factor']:.3f} PV={v['pv_yield_kwh_per_kwp']:.0f} "
              f"gas Jan/Jul={v['gas_monthly_share'][0]:.3f}/{v['gas_monthly_share'][6]:.3f}")


if __name__ == "__main__":
    main()
