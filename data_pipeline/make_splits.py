"""Synthetic customers and the single train/val/test split everyone uses (BUILD_GUIDE P1.8, P1.10).

Applied to ALL EPC properties (not just the product sample), because the rating, recommender and
value models train on every certificate/sale and must respect the same split.

Customers: 85% own 1 property, 12% own 2, 3% own 3-5; a customer's properties are in the same
region (realistic for a mortgage book, and it makes customer-level leakage a real risk to guard).
Split: 70/15/15 by customer_id (a customer's properties never straddle splits), seeded.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SIZES = np.array([1, 2, 3, 4, 5])
SIZE_P = np.array([0.85, 0.12, 0.01, 0.01, 0.01])
SPLIT_P = {"train": 0.70, "val": 0.15, "test": 0.15}


def assign_customers(props: pd.DataFrame, rng: np.random.Generator) -> pd.Series:
    """Vectorised: shuffle properties within region, then cut into customer-sized runs."""
    out = np.empty(len(props), dtype=object)
    next_id = 10001
    for _region, idx in sorted(
        props.groupby("region", dropna=False).indices.items(), key=lambda kv: str(kv[0])
    ):
        idx = rng.permutation(idx)
        sizes = rng.choice(SIZES, size=len(idx), p=SIZE_P)  # more than enough runs
        ends = np.cumsum(sizes)
        k = int(np.searchsorted(ends, len(idx))) + 1
        owner = np.repeat(np.arange(k), sizes[:k])[: len(idx)]
        out[idx] = np.char.add("C", (next_id + owner).astype(str))
        next_id += k
    return pd.Series(out, index=props.index)


def make_splits(props: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Assign each customer to train/val/test with a seeded hash-free random draw."""
    rng = np.random.default_rng(seed + 7)
    customers = np.sort(props["customer_id"].unique())
    draw = rng.choice(list(SPLIT_P), size=len(customers), p=list(SPLIT_P.values()))
    split = pd.Series(draw, index=customers)
    out = props[["property_id", "customer_id"]].assign(split=props["customer_id"].map(split).values)
    assert out.groupby("customer_id")["split"].nunique().max() == 1  # leakage guard
    assert out["property_id"].is_unique
    return out
