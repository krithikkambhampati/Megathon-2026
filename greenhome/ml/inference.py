"""Inference wrappers for the Part 3 models (BUILD_GUIDE section 7.6). Load once, predict in batches.

Every wrapper accepts homes as a pandas DataFrame with contract column names, OR a list of dicts /
pydantic models (HomeInput / CleanHome.home); `to_frame` normalises them. Features are always built by
greenhome.ml.features, and each model's saved column list is checked against it at load time, so a
train/serve feature mismatch fails loudly instead of silently predicting garbage.

    from greenhome.ml.inference import Models
    m = Models.load()                         # all models, ~1 s
    sap = m.rating.predict_sap(homes)                       # (n,)
    after = m.energy.predict_after(homes, elec_kwh, gas_kwh, packages)   # DataFrame electricity_kwh, gas_kwh
    p = m.recommender.predict_proba(homes)                  # DataFrame n x 7 retrofits (NaN: no model)
    lp = m.value.predict_log_price(homes, ratings, "2026-07")   # (20, n) ensemble log GBP
"""

from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from greenhome.ml import features as F

ROOT = Path(__file__).resolve().parents[2]
MODELS = Path(os.environ.get("GREENHOME_MODELS_DIR", ROOT / "models"))
BANDS = [(92, "A"), (81, "B"), (69, "C"), (55, "D"), (39, "E"), (21, "F"), (-1, "G")]


def to_frame(homes) -> pd.DataFrame:
    if isinstance(homes, pd.DataFrame):
        return homes.reset_index(drop=True)
    rows = []
    for h in homes:
        if hasattr(h, "model_dump"):
            h = h.model_dump(mode="json")
        h = dict(h)
        h.pop("energy", None)
        rows.append(h)
    return pd.DataFrame(rows)


def sap_to_band(sap) -> np.ndarray:
    s = np.asarray(sap, float)
    out = np.full(len(s), "G", dtype=object)
    for lo, b in reversed(BANDS):
        out[s >= lo] = b
    return out


def _booster(path: Path) -> lgb.Booster:
    """Load a LightGBM text model, gzip-compressed (.txt.gz, as committed) or plain."""
    if path.suffix == ".gz":
        with gzip.open(path, "rt") as fh:
            return lgb.Booster(model_str=fh.read())
    return lgb.Booster(model_file=str(path))


@dataclass
class _Loaded:
    boosters: list[lgb.Booster]
    columns: list[str]
    manifest: dict

    @classmethod
    def load(cls, name: str) -> _Loaded:
        d = MODELS / name
        man = json.loads((d / "manifest.json").read_text())
        feats = json.loads((d / "features.json").read_text())
        boosters = [_booster(d / f) for f in man["model_files"]]
        return cls(boosters, feats["columns"], man)

    def check(self, X: pd.DataFrame, name: str) -> pd.DataFrame:
        if list(X.columns) != self.columns:
            raise RuntimeError(
                f"{name}: feature mismatch between greenhome.ml.features and the trained model. "
                f"Retrain or fix features.py. model={self.columns} built={list(X.columns)}"
            )
        return X

    @property
    def version(self) -> str:
        return self.manifest["version"]


class RatingModel:
    """M4: SAP points from home features. Part 2 anchors to the user's stated band and uses DELTAS for
    post-retrofit ratings (BUILD_GUIDE P2.8 step 8)."""

    def __init__(self):
        self.m = _Loaded.load("rating")
        self.version = self.m.version

    def predict_sap(self, homes) -> np.ndarray:
        X = self.m.check(F.rating_features(to_frame(homes)), "rating")
        return np.clip(self.m.boosters[0].predict(X), 1, 100)


class EnergyModel:
    """M1: annual grid electricity import and gas after a retrofit package, anchored to the home's own
    annualised baseline. An empty package returns the baseline unchanged."""

    def __init__(self):
        self.e, self.g = _Loaded.load("energy_elec"), _Loaded.load("energy_gas")
        self.version = self.e.version

    def predict_after(self, homes, elec_before, gas_before, packages: list) -> pd.DataFrame:
        df = to_frame(homes)
        eb = pd.Series(np.asarray(elec_before, float))
        gb = pd.Series(np.asarray(gas_before, float))
        pk = [frozenset(p) for p in packages]
        X = F.energy_features(df, eb, gb, pk)
        # each fuel is predicted as a ratio to its OWN baseline (no cross-fuel leakage)
        el = np.clip(self.e.boosters[0].predict(self.e.check(X, "energy_elec")), 0, None) * eb.to_numpy()
        ga = np.where(
            gb.to_numpy() > 1.0,
            np.clip(
                self.g.boosters[0].predict(self.g.check(F.mask_for_fuel(X, "gas"), "energy_gas")), 0, None
            )
            * gb.to_numpy(),
            0.0,
        )
        # a fuel with no relevant retrofit in the package keeps its baseline exactly (e.g. solar-only -> gas
        # unchanged); the models were never trained on packages with no relevant retrofit
        no_gas = np.array([not (set(p) - set(F.FUEL_IRRELEVANT_RETROFITS["gas"])) for p in pk])
        no_el = np.array([not (set(p) - set(F.FUEL_IRRELEVANT_RETROFITS["elec"])) for p in pk])
        el = np.where(no_el, eb, el)
        ga = np.where(no_gas, gb, ga)
        return pd.DataFrame({"electricity_kwh": el, "gas_kwh": ga, "purchased_kwh": el + ga})


class RecommenderModel:
    """M2: P(an EPC assessor would recommend r | home), per retrofit. Call only for rule-feasible r."""

    def __init__(self):
        self.models = {
            r: _Loaded.load(f"recommender/{r}")
            for r in F.RETROFITS
            if (MODELS / "recommender" / r / "manifest.json").exists()
        }
        self.version = max(m.version for m in self.models.values())

    def predict_proba(self, homes) -> pd.DataFrame:
        X = F.recommender_features(to_frame(homes))
        out = pd.DataFrame(index=X.index, columns=F.RETROFITS, dtype=float)
        for r, m in self.models.items():
            out[r] = m.boosters[0].predict(m.check(X, f"recommender/{r}"))
        return out


class ValueModel:
    """M3: ensemble log price at a valuation month. Part 2 turns before/after differences into a range."""

    def __init__(self):
        self.m = _Loaded.load("value")
        self.version = self.m.version
        self.region_hpi = self.m.manifest["region_hpi_codes"]
        # regional UK HPI series ships inside the model folder, so the model is self-contained
        h = pd.read_csv(MODELS / "value" / "hpi_region.csv", dtype={"month": str})
        self.hpi = h.set_index(["area_code", "month"])["index"]

    def predict_log_price(self, homes, ratings, as_of: str) -> np.ndarray:
        df = to_frame(homes)
        n = len(df)
        p = pd.Period(as_of, freq="M")
        month_index = pd.Series([(p.year - 2015) * 12 + p.month - 1] * n, dtype=float)
        hpi = pd.Series(
            [self.hpi.get((self.region_hpi.get(r), as_of), np.nan) for r in df["region"]], dtype=float
        )
        X = self.m.check(F.value_features(df, pd.Series(list(ratings)), month_index, hpi), "value")
        return np.vstack([b.predict(X) for b in self.m.boosters])

    def uplift_pct(self, homes, rating_before, rating_after, as_of: str) -> pd.DataFrame:
        d = self.predict_log_price(homes, rating_after, as_of) - self.predict_log_price(
            homes, rating_before, as_of
        )
        u = (np.exp(d) - 1) * 100
        return pd.DataFrame(
            {
                "uplift_pct_low": np.percentile(u, 10, axis=0),
                "uplift_pct_mid": np.median(u, axis=0),
                "uplift_pct_high": np.percentile(u, 90, axis=0),
            }
        )


@dataclass
class Models:
    rating: RatingModel
    energy: EnergyModel
    recommender: RecommenderModel
    value: ValueModel

    @classmethod
    def load(cls) -> Models:
        return cls(RatingModel(), EnergyModel(), RecommenderModel(), ValueModel())

    def versions(self) -> dict[str, str]:
        return {
            "rating": self.rating.version,
            "energy": self.energy.version,
            "recommender": self.recommender.version,
            "value": self.value.version,
        }
