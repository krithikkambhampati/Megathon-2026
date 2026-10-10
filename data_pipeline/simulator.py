"""Retrofit simulator: post-retrofit annual fuel use per (home, package), with hidden factors.

For a package S applied to home p (README P1.9):
  1. space heat after = baseline space heat x prod_{r in S, r acts on space heating} (1 - effect_r)
       effect_r = lo + u_r * (hi - lo), [lo, hi] from the catalogue for the home's STARTING state,
       u_r a hidden per-home draw. Fabric/glazing/control savings therefore compound multiplicatively
       (package saving < sum of single savings).
  2. home after = apply_retrofits(p, S): heating system, renewables, insulation states change.
  3. delivered fuel is recomputed for the after-home: a heat pump moves (space heat + hot water)
       from gas to electricity at the home's hidden SCOP, which is penalised if the AFTER fabric is
       still poor. So insulating first makes the heat pump both smaller and more efficient. Solar
       adds generation, and self-consumption cuts grid imports; underlying demand is unchanged.
Cooking gas stays after a heat pump (the gas meter remains), so gas rarely reaches exactly 0.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_pipeline import physics as ph
from data_pipeline.kernels_tmp import apply_retrofits

SPACE_HEAT_RETROFITS = {
    "loft_insulation": "roof_insulation",
    "cavity_wall_insulation": "wall_insulation",
    "solid_wall_insulation": "wall_insulation",
    "double_glazing": "glazing",
    "smart_thermostat": "smart_controls",
}


def effect_fraction(p: pd.DataFrame, h: pd.DataFrame, retrofit: str) -> np.ndarray:
    """Per-home fractional cut in space heat for one retrofit (0 where the state has no range)."""
    ranges = ph.CATALOGUE[retrofit]["effect_range_frac"]
    state = p[SPACE_HEAT_RETROFITS[retrofit]]
    lo = state.map({k: v[0] for k, v in ranges.items()}).fillna(0.0).to_numpy()
    hi = state.map({k: v[1] for k, v in ranges.items()}).fillna(0.0).to_numpy()
    return lo + h[f"u_{retrofit}"].to_numpy() * (hi - lo)


def simulate(p: pd.DataFrame, h: pd.DataFrame, cal_sh, cal_el, package: frozenset[str]) -> pd.DataFrame:
    """Annual fuel after applying `package` to every home in p (row-aligned with h)."""
    eu0 = ph.end_uses(p, h, cal_sh, cal_el)
    keep = np.ones(len(p))
    for r in package & SPACE_HEAT_RETROFITS.keys():
        keep *= 1.0 - effect_fraction(p, h, r)
    q = apply_retrofits(p, package)
    eu1 = ph.end_uses(q, h, cal_sh, cal_el)      # recomputed only for PV generation
    eu1["space_heat"] = eu0["space_heat"].to_numpy() * keep
    eu1["hot_water"] = eu0["hot_water"].to_numpy()
    eu1["appliances"] = eu0["appliances"].to_numpy()
    return ph.delivered(q, h, eu1)


def sample_packages(feasible: pd.DataFrame, k: int, rng: np.random.Generator) -> list[list[frozenset[str]]]:
    """Per home: every feasible single retrofit, the full feasible package, plus random subsets, up to k."""
    out = []
    cols = np.array(feasible.columns)
    for row in feasible.to_numpy():
        f = list(cols[row])
        pk = {frozenset([r]) for r in f}
        if f:
            pk.add(frozenset(f))
        tries = 0
        while len(pk) < min(k, 2 ** len(f) - 1) and tries < 50:
            m = rng.integers(2, len(f) + 1) if len(f) >= 2 else 1
            pk.add(frozenset(rng.choice(f, size=m, replace=False)))
            tries += 1
        out.append(sorted(pk, key=lambda s: (len(s), sorted(s)))[: max(k, len(f) + 1)])
    return out
