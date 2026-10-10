"""Shared training utilities (Part 3): data loading, artefact saving, bootstrap CIs.

Conventions (README P3.0): train on `train`, early-stop/tune on `val`, report val AND test; never tune on
test. LightGBM is seeded and deterministic. Every model directory holds model.txt (or model_XX.txt),
features.json (ordered columns, categories, monotone constraints) and manifest.json (metrics, versions).
CIs: bootstrap over PROPERTIES (rows of one property are resampled together), 200 resamples.
"""
from __future__ import annotations

import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
MODELS = ROOT / "models"
PRED = ROOT / "outputs" / "test_predictions"
REPORTS = ROOT / "reports"
SEED = 42

BASE_PARAMS = dict(seed=SEED, deterministic=True, force_row_wise=True, num_threads=16, verbose=-1,
                   learning_rate=0.05, num_leaves=63, min_data_in_leaf=200, feature_fraction=0.9,
                   bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0)


def splits() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / "splits.parquet")[["property_id", "split"]]


def train_lgb(X_tr, y_tr, X_va, y_va, params: dict, rounds: int = 3000, w_tr=None, w_va=None) -> lgb.Booster:
    dtr = lgb.Dataset(X_tr, y_tr, weight=w_tr, free_raw_data=False)
    dva = lgb.Dataset(X_va, y_va, weight=w_va, reference=dtr)
    t = time.time()
    b = lgb.train({**BASE_PARAMS, **params}, dtr, num_boost_round=rounds, valid_sets=[dva],
                  callbacks=[lgb.early_stopping(100, verbose=False), lgb.log_evaluation(0)])
    print(f"  trained {b.best_iteration} rounds in {time.time() - t:.0f}s")
    return b


def save_model(name: str, boosters: list[lgb.Booster] | lgb.Booster, X: pd.DataFrame, constraints: list[int],
               metrics: dict, extra: dict | None = None) -> Path:
    d = MODELS / name
    d.mkdir(parents=True, exist_ok=True)
    boosters = boosters if isinstance(boosters, list) else [boosters]
    files = []
    for i, b in enumerate(boosters):
        f = "model.txt" if len(boosters) == 1 else f"model_{i:02d}.txt"
        b.save_model(str(d / f), num_iteration=b.best_iteration or None)
        files.append(f)
    feats = {"columns": list(X.columns),
             "categorical": {c: list(X[c].cat.categories) for c in X.columns if isinstance(X[c].dtype, pd.CategoricalDtype)},
             "monotone_constraints": dict(zip(X.columns, constraints))}
    (d / "features.json").write_text(json.dumps(feats, indent=2))
    data_manifest = json.loads((PROCESSED / "MANIFEST.json").read_text())
    man = {"name": name, "version": datetime.now(timezone.utc).strftime("%Y%m%d%H%M"),
           "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model_files": files,
           "seed": SEED, "lightgbm": lgb.__version__, "python": platform.python_version(),
           "data_manifest_created_at": data_manifest["created_at"], "metrics": metrics, **(extra or {})}
    (d / "manifest.json").write_text(json.dumps(man, indent=2, default=float))
    return d


def bootstrap_ci(groups: np.ndarray, stat_parts: dict[str, np.ndarray], stat, n: int = 200) -> tuple[float, float]:
    """95% CI of stat(**sums) where sums are per-group sums of each part, resampling groups."""
    df = pd.DataFrame(stat_parts)
    df["g"] = groups
    agg = df.groupby("g").sum()
    rng = np.random.default_rng(SEED)
    vals = []
    for _ in range(n):
        idx = rng.integers(0, len(agg), len(agg))
        s = agg.iloc[idx].sum()
        vals.append(stat(s))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def regression_metrics(y, p, groups) -> dict:
    y, p = np.asarray(y, float), np.asarray(p, float)
    e = p - y
    ss_tot = ((y - y.mean()) ** 2).sum()
    m = {"n": int(len(y)), "mae": float(np.abs(e).mean()), "rmse": float(np.sqrt((e ** 2).mean())),
         "r2": float(1 - (e ** 2).sum() / ss_tot)}
    m["mae_ci95"] = bootstrap_ci(groups, {"ae": np.abs(e), "n": np.ones_like(e)}, lambda s: s["ae"] / s["n"])
    return m
