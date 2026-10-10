"""Real (Part 3) models behind Part 2's interfaces (README section 7.6, D12).

Engine.from_config() calls `load_models(models_dir)` when config/global.yaml has `models: real`.
Each adapter implements the matching Protocol in greenhome/ml/protocols.py exactly, converting
CleanHome objects to the contract-column frame that greenhome.ml.features was trained on.
Models are loaded once; every call is batched.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from greenhome.contracts import CleanHome, EnergyRating, FuelEnergy, Retrofit
from greenhome.ml import inference as I
from greenhome.ml.protocols import Models


def homes_frame(homes: list[CleanHome]) -> pd.DataFrame:
    """CleanHome list -> contract-column frame (HomeInput fields + gas_connected)."""
    rows = []
    for c in homes:
        h = c.home.model_dump(mode="json")
        h.pop("energy", None)
        gas = c.energy.gas_kwh
        # HomeInput has no gas-connection field: connected if gas is the main fuel or any gas is metered
        h["gas_connected"] = h.get("main_fuel") == "mains_gas" or (gas is not None and gas > 0)
        rows.append(h)
    return pd.DataFrame(rows)


def _val(x) -> str:
    return getattr(x, "value", x)


class RealRating:
    def __init__(self) -> None:
        self._m = I.RatingModel()
        self.version = f"rating-{self._m.version}"

    def predict_sap(self, homes: list[CleanHome]) -> list[float]:
        if not homes:
            return []
        return [float(v) for v in self._m.predict_sap(homes_frame(homes))]


class RealEnergy:
    def __init__(self) -> None:
        self._m = I.EnergyModel()
        self.version = f"energy-{self._m.version}"

    def predict_after(self, homes: list[CleanHome], packages: list[frozenset[Retrofit]]) -> list[FuelEnergy]:
        if not homes:
            return []
        if len(homes) != len(packages):
            raise ValueError("len(homes) != len(packages)")
        eb = [c.energy.electricity_kwh or 0.0 for c in homes]
        gb = [c.energy.gas_kwh or 0.0 for c in homes]
        out = self._m.predict_after(homes_frame(homes), eb, gb, [frozenset(_val(r) for r in p) for p in packages])
        return [FuelEnergy(electricity_kwh=float(r.electricity_kwh), gas_kwh=float(r.gas_kwh),
                           purchased_kwh=float(r.purchased_kwh)) for r in out.itertuples()]


class RealRecommender:
    def __init__(self) -> None:
        self._m = I.RecommenderModel()
        self.version = f"recommender-{self._m.version}"

    def predict_proba(self, homes: list[CleanHome]) -> list[dict[Retrofit, float]]:
        if not homes:
            return []
        p = self._m.predict_proba(homes_frame(homes)).fillna(0.0)
        return [{Retrofit(r): float(row[r]) for r in p.columns} for _, row in p.iterrows()]


class RealValue:
    def __init__(self) -> None:
        self._m = I.ValueModel()
        self.version = f"value-{self._m.version}"

    def predict_log_price(self, homes: list[CleanHome], ratings: list[EnergyRating], as_of: str) -> np.ndarray:
        if not homes:
            return np.empty((len(self._m.m.boosters), 0))
        return self._m.predict_log_price(homes_frame(homes), [_val(r) for r in ratings], as_of[:7])


def load_models(models_dir: str | Path | None = None) -> Models:
    if models_dir is not None and Path(models_dir).resolve() != I.MODELS.resolve():
        I.MODELS = Path(models_dir)
    return Models(energy=RealEnergy(), rating=RealRating(), recommender=RealRecommender(), value=RealValue())
