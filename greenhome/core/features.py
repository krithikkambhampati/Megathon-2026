"""Model feature kernel (README P2.3, §7.1 "Feature building").

The ONLY builder of model inputs, for training (P3), the simulator (P1) and serving (P2). Column order and
categorical dtypes are fixed, so train and serve frames are identical in layout. Missing → NaN, never 0.
Never includes hidden simulator factors or model outputs (sap_estimate).
"""

from __future__ import annotations

import math

import pandas as pd

from greenhome.config import get_config
from greenhome.contracts import (
    CleanHome,
    HeatingSystem,
    MainFuel,
    PropertyType,
    Region,
    Retrofit,
    RoofType,
    WallType,
)
from greenhome.core.score import insulation_sub_score

CATEGORICAL: dict[str, list[str]] = {
    "property_type": [e.value for e in PropertyType],
    "region": [e.value for e in Region],
    "roof_type": [e.value for e in RoofType],
    "wall_type": [e.value for e in WallType],
    "heating_system": [e.value for e in HeatingSystem],
    "main_fuel": [e.value for e in MainFuel],
}
ORDINAL: tuple[str, ...] = (
    "age_band", "energy_rating", "roof_insulation", "wall_insulation", "glazing", "renewables",
    "smart_controls",
)
NUMERIC: tuple[str, ...] = (
    "floor_area_m2", "log_floor_area", "bedrooms", "listed_or_conservation", "outdoor_space",
    "insulation_sub_score", "hdd_factor", "pv_yield_kwh_per_kwp", "baseline_electricity_kwh",
    "baseline_gas_kwh", "baseline_purchased_kwh", "intensity_kwh_m2", "elec_share",
)
RETROFIT_COLUMNS: tuple[str, ...] = tuple(f"r_{r.value}" for r in Retrofit)
FEATURE_COLUMNS: list[str] = [*CATEGORICAL, *ORDINAL, *NUMERIC, *RETROFIT_COLUMNS]

_YES_NO = {"yes": 1.0, "no": 0.0}
_NAN = float("nan")


def _nan(x: float | None) -> float:
    return _NAN if x is None else float(x)


def _row(clean: CleanHome, package: frozenset[str], ordinals: dict[str, dict[str, float]]) -> dict:
    cfg = get_config()
    h, e = clean.home, clean.energy
    region = cfg.region(h.region)
    purchased = e.purchased_kwh
    elec_share = e.electricity_kwh / purchased if purchased and e.electricity_kwh is not None else None
    row: dict = {c: getattr(h, c) for c in CATEGORICAL}
    row |= {c: ordinals[c].get(getattr(h, c), _NAN) for c in ORDINAL}
    row |= {
        "floor_area_m2": _nan(h.floor_area_m2),
        "log_floor_area": _NAN if h.floor_area_m2 is None else math.log(h.floor_area_m2),
        "bedrooms": _nan(h.bedrooms),
        "listed_or_conservation": _YES_NO.get(h.listed_or_conservation, _NAN),
        "outdoor_space": _YES_NO.get(h.outdoor_space, _NAN),
        "insulation_sub_score": _nan(
            insulation_sub_score(h.roof_type, h.roof_insulation, h.wall_type, h.wall_insulation)
        ),
        "hdd_factor": region.hdd_factor,
        "pv_yield_kwh_per_kwp": region.pv_yield_kwh_per_kwp,
        "baseline_electricity_kwh": _nan(e.electricity_kwh),
        "baseline_gas_kwh": _nan(e.gas_kwh),
        "baseline_purchased_kwh": _nan(purchased),
        "intensity_kwh_m2": _nan(clean.intensity_kwh_m2),
        "elec_share": _nan(elec_share),
    }
    row |= {f"r_{r.value}": int(r.value in package) for r in Retrofit}
    return row


def build_model_features(
    homes: list[CleanHome], packages: list[frozenset[str]] | None = None
) -> pd.DataFrame:
    """One row per home, columns exactly FEATURE_COLUMNS. packages None → no retrofits (all r_* = 0)."""
    if packages is not None and len(packages) != len(homes):
        raise ValueError(f"len(packages)={len(packages)} != len(homes)={len(homes)}")
    cfg = get_config()
    ordinals = {c: {v: float(i) for i, v in enumerate(cfg.quality_order(c))} for c in ORDINAL}
    pkgs = [frozenset(str(r) for r in p) for p in packages] if packages else [frozenset()] * len(homes)
    rows = [_row(h, p, ordinals) for h, p in zip(homes, pkgs, strict=True)]
    df = pd.DataFrame(rows, columns=FEATURE_COLUMNS)
    return df.astype(
        {c: pd.CategoricalDtype(cats) for c, cats in CATEGORICAL.items()}
        | {c: "float64" for c in (*ORDINAL, *NUMERIC)}
        | {c: "int64" for c in RETROFIT_COLUMNS}
    )
