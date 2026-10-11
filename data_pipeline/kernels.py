"""Vectorised access to Part 2's shared kernels for the data pipeline.

greenhome.core.feasibility.feasible_set and greenhome.core.transitions.apply_retrofits are the single
source of truth (BUILD_GUIDE P2.3/P2.7), so "feasible" in the simulator labels is exactly "feasible" in the app.
They work on one HomeInput at a time; here they run once per unique combination of the fields they read
(a few thousand across millions of rows) and the result is broadcast back to every row.
"""

from __future__ import annotations

import pandas as pd

from greenhome.contracts import HomeInput
from greenhome.core.feasibility import feasible_set
from greenhome.core.transitions import apply_retrofits

RETROFITS = [
    "loft_insulation",
    "cavity_wall_insulation",
    "solid_wall_insulation",
    "double_glazing",
    "air_source_heat_pump",
    "solar_pv",
    "smart_thermostat",
]
# categorical HomeInput fields the kernels read or change (numeric fields never affect them)
STATE = [
    "property_type",
    "roof_type",
    "roof_insulation",
    "wall_type",
    "wall_insulation",
    "glazing",
    "heating_system",
    "main_fuel",
    "renewables",
    "smart_controls",
    "listed_or_conservation",
    "outdoor_space",
]


def _home(row: dict) -> HomeInput:
    return HomeInput.model_validate({k: (None if pd.isna(v) else v) for k, v in row.items()})


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and v != v)


def _unique_state(p: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    s = p.reindex(columns=STATE).astype(object)
    s = s.map(lambda v: None if _missing(v) else v)
    key = s.map(lambda v: "~" if v is None else str(v)).agg("|".join, axis=1)
    uniq = s.loc[~key.duplicated()].assign(_key=key[~key.duplicated()]).reset_index(drop=True)
    return uniq, key


def feasible_frame(p: pd.DataFrame) -> pd.DataFrame:
    """Boolean homes x retrofits: True if Part 2 says feasible or needs_survey."""
    uniq, key = _unique_state(p)
    rows = []
    for rec in uniq.drop(columns="_key").to_dict("records"):
        fs = feasible_set(_home(rec))
        rows.append({r: fs[r][0] in ("feasible", "needs_survey") for r in RETROFITS})
    table = pd.DataFrame(rows, index=uniq["_key"])
    return table.reindex(key.to_numpy()).set_axis(p.index).astype(bool)


def apply_frame(p: pd.DataFrame, package: frozenset[str]) -> pd.DataFrame:
    """Post-retrofit state for every row (only STATE columns change; others are copied)."""
    uniq, key = _unique_state(p)
    after = []
    for rec in uniq.drop(columns="_key").to_dict("records"):
        h = apply_retrofits(_home(rec), package).model_dump(mode="json")
        after.append({c: h.get(c) for c in STATE})
    table = pd.DataFrame(after, index=uniq["_key"])
    q = p.copy()
    mapped = table.reindex(key.to_numpy()).set_axis(p.index)
    for c in STATE:
        if c in q.columns:
            q[c] = mapped[c].to_numpy()
    return q
