"""Synthetic monthly meter readings (grid electricity import + mains gas) with documented missingness.

Annual delivered fuel comes from physics.delivered() (calibrated to NEED by calibrate.py). It is
split into months using the regional profiles in config/regions.yaml:
  gas          gas_monthly_share (HDD-weighted heating + hot water)
  electricity  appliance/lighting demand x LCL smart-meter shape, electric heating x gas-style heat
               shape, minus PV self-consumption x PVGIS monthly shape
Each month gets +/-3% multiplicative measurement noise.

Missingness patterns (README P1.7; seeded; missing = row value null, NEVER zero):
  70% complete 12 months | 15% 1-3 random months missing | 7% 4-8 consecutive months missing
   3% gas column missing although gas is used | 2% only annual totals (no monthly)
   3% no energy data at all
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_pipeline import physics as ph

PATTERNS = [("complete", 0.70), ("random_gaps", 0.15), ("block_gap", 0.07),
            ("gas_missing", 0.03), ("annual_only", 0.02), ("no_data", 0.03)]
NOISE_SD = 0.03


def months_ending(end_month: str) -> list[str]:
    end = pd.Period(end_month, freq="M")
    return [str(end - k) for k in range(11, -1, -1)]


def _share_matrix(regions: pd.Series, key: str, months: list[str]) -> np.ndarray:
    """(n_homes, 12) shares aligned to the calendar months of the meter year."""
    month_idx = [int(m[5:7]) - 1 for m in months]
    table = {r: np.asarray(v[key])[month_idx] for r, v in ph.REGIONS["regions"].items()}
    nat = np.asarray(ph.REGIONS["national"]["gas_monthly_share" if key == "gas_monthly_share"
                                         else "elec_monthly_share"])[month_idx]
    return np.vstack([table.get(r, nat) for r in regions])


def monthly_readings(p: pd.DataFrame, eu: pd.DataFrame, fuel: pd.DataFrame, end_month: str,
                     rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (long monthly table, per-home missingness pattern table)."""
    months = months_ending(end_month)
    gas_sh = _share_matrix(p["region"], "gas_monthly_share", months)
    el_sh = _share_matrix(p["region"], "elec_monthly_share", months)
    pv_sh = _share_matrix(p["region"], "pv_monthly_share", months)

    heat_elec = (fuel["electricity_demand_kwh"] - eu["appliances"]).to_numpy()[:, None]
    elec = (eu["appliances"].to_numpy()[:, None] * el_sh + heat_elec * gas_sh
            - fuel["pv_self_consumed_kwh"].to_numpy()[:, None] * pv_sh)
    gas = fuel["gas_kwh"].to_numpy()[:, None] * gas_sh
    elec = np.clip(elec * rng.normal(1, NOISE_SD, elec.shape), 0, None)
    gas = np.clip(gas * rng.normal(1, NOISE_SD, gas.shape), 0, None)

    n = len(p)
    names, probs = zip(*PATTERNS)
    pattern = rng.choice(names, size=n, p=probs)
    e_mask = np.ones((n, 12), bool)
    g_mask = np.ones((n, 12), bool)
    for i, pat in enumerate(pattern):
        if pat == "random_gaps":
            drop = rng.choice(12, size=rng.integers(1, 4), replace=False)
            e_mask[i, drop] = g_mask[i, drop] = False
        elif pat == "block_gap":
            k = rng.integers(4, 9)
            s = rng.integers(0, 12 - k + 1)
            e_mask[i, s:s + k] = g_mask[i, s:s + k] = False
        elif pat == "gas_missing":
            g_mask[i, :] = False
        elif pat in ("annual_only", "no_data"):
            e_mask[i, :] = g_mask[i, :] = False
    no_gas = fuel["gas_kwh"].to_numpy() <= 0
    gas = np.where(no_gas[:, None], 0.0, gas)    # genuinely no gas supply: 0 is a true reading

    rows = pd.DataFrame({
        "property_id": np.repeat(p["property_id"].to_numpy(), 12),
        "month": np.tile(months, n),
        "electricity_kwh": np.where(e_mask, elec, np.nan).ravel(),
        "gas_kwh": np.where(g_mask, gas, np.nan).ravel(),
    })
    rows.loc[np.repeat(no_gas, 12) & rows["electricity_kwh"].notna(), "gas_kwh"] = 0.0
    keep = ~(rows["electricity_kwh"].isna() & rows["gas_kwh"].isna())
    rows = rows[keep].reset_index(drop=True)          # fully missing months -> no row at all

    meta = pd.DataFrame({
        "property_id": p["property_id"].to_numpy(),
        "missingness_pattern": pattern,
        # annual totals the customer would type in, when they have no monthly data
        "annual_electricity_kwh": np.where(pattern == "annual_only", elec.sum(1).round(0), np.nan),
        "annual_gas_kwh": np.where(pattern == "annual_only", gas.sum(1).round(0), np.nan),
        # noiseless truth for evaluation of annualisation (NOT an input)
        "true_annual_electricity_kwh": elec.sum(1),
        "true_annual_gas_kwh": gas.sum(1),
    })
    return rows, meta
