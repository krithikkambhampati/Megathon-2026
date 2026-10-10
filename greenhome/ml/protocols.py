"""Model interfaces (README §7.6). P2 codes against these; P3's wrappers and P2's stubs implement them.

All calls are batched: one `analyse()` makes at most 3 calls per model, each < 50 ms on a laptop.
Retrofit keys/values are the §7.2 strings (Retrofit is a str Enum, so either form works).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from greenhome.contracts import CleanHome, EnergyRating, FuelEnergy, Retrofit


@runtime_checkable
class EnergyModel(Protocol):
    version: str

    def predict_after(self, homes: list[CleanHome], packages: list[frozenset[Retrofit]]) -> list[FuelEnergy]:
        """Batched. len(homes) == len(packages). Empty package → returns baseline unchanged.
        Uses the home's ANNUALISED baseline (home.energy) as anchor. Must clip outputs at >= 0."""
        ...


@runtime_checkable
class RatingModel(Protocol):
    version: str

    def predict_sap(self, homes: list[CleanHome]) -> list[float]:
        """Raw SAP prediction 1–100 from features (no anchoring; P2 anchors to the stated band)."""
        ...


@runtime_checkable
class RecommenderModel(Protocol):
    version: str

    def predict_proba(self, homes: list[CleanHome]) -> list[dict[Retrofit, float]]:
        """P(assessor would recommend r | home). Called only for rule-feasible r, but must return all keys."""
        ...


@runtime_checkable
class ValueModel(Protocol):
    version: str

    def predict_log_price(
        self, homes: list[CleanHome], ratings: list[EnergyRating], as_of: str
    ) -> np.ndarray:
        """Shape (n_ensemble, n_homes). log(£) at as_of. P2 turns before/after differences into a range."""
        ...


@dataclass(frozen=True)
class Models:
    """The four models the engine needs. Stubs and real models go through the same container."""

    energy: EnergyModel
    rating: RatingModel
    recommender: RecommenderModel
    value: ValueModel

    def versions(self) -> dict[str, str]:
        return {
            "energy": self.energy.version,
            "rating": self.rating.version,
            "recommender": self.recommender.version,
            "value": self.value.version,
        }
