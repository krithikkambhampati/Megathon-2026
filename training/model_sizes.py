"""Count stored parameters of every trained model (BUILD_GUIDE deliverable C / MODELS.md).

A gradient-boosted tree stores, per internal split, a feature index + threshold (2 numbers) and, per
leaf, an output value (1 number). Parameters = 2 x splits + leaves, summed over all trees.
"""

from __future__ import annotations

import pandas as pd

from greenhome.ml.inference import _booster
from training.common import MODELS, REPORTS


def main() -> None:
    rows = []
    for f in sorted(MODELS.rglob("model*.txt*")):
        b = _booster(f)
        trees = b.dump_model()["tree_info"]
        leaves = sum(t["num_leaves"] for t in trees)
        splits = sum(t["num_leaves"] - 1 for t in trees)
        rows.append(
            {
                "model": str(f.parent.relative_to(MODELS)),
                "file": f.name,
                "trees": len(trees),
                "leaves": leaves,
                "parameters": 2 * splits + leaves,
                "size_mb": f.stat().st_size / 1e6,
            }
        )
    df = pd.DataFrame(rows)
    by = df.groupby("model").agg(
        files=("file", "size"),
        trees=("trees", "sum"),
        leaves=("leaves", "sum"),
        parameters=("parameters", "sum"),
        size_mb=("size_mb", "sum"),
    )
    by.loc["TOTAL"] = by.sum()
    by["size_mb"] = by["size_mb"].round(2)
    by.to_csv(REPORTS / "model_sizes.csv")
    print(by.to_string())


if __name__ == "__main__":
    main()
