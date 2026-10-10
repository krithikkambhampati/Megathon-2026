"""M4: SAP rating model on real EPC certificates (README P3.1).

Target: SAP points (1-100). Features: home only (greenhome.ml.features.rating_features), fields available
in HomeInput. Monotone +1 on insulation/glazing/controls/renewables ordinals: a better state can never
lower the predicted SAP, so retrofit SAP gains are always >= 0 for those measures.
Baseline: median SAP by age band x property type (train).
Extra validation: model-implied SAP gain per retrofit vs REAL gains observed between repeat EPCs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from data_pipeline.kernels import apply_frame as apply_retrofits
from data_pipeline.kernels import feasible_frame as feasible_set
from greenhome.ml import features as F
from training.common import PRED, PROCESSED, REPORTS, regression_metrics, save_model, splits, train_lgb

BANDS = [(92, "A"), (81, "B"), (69, "C"), (55, "D"), (39, "E"), (21, "F"), (-1, "G")]


def sap_to_band(s) -> np.ndarray:
    s = np.asarray(s, float)
    out = np.full(len(s), "G", dtype=object)
    for lo, b in reversed(BANDS):
        out[s >= lo] = b
    return out


def band_metrics(y, p) -> dict:
    by, bp = sap_to_band(y), sap_to_band(p)
    idx = {b: i for i, (_, b) in enumerate(BANDS)}
    d = np.abs(np.vectorize(idx.get)(by) - np.vectorize(idx.get)(bp))
    return {"band_accuracy": float((d == 0).mean()), "within_one_band": float((d <= 1).mean())}


def main() -> None:
    c = pd.read_parquet(PROCESSED / "epc_certificates_model.parquet").merge(splits(), on="property_id")
    X = F.rating_features(c)
    y = c["sap_score"].astype(float)
    tr, va, te = (c["split"] == s for s in ("train", "val", "test"))
    spec = {q: 1 for q in F.RATING_QUALITY}
    mono = F.monotone_constraints(list(X.columns), spec)
    print(f"M4 rating: train {tr.sum():,} / val {va.sum():,} / test {te.sum():,} certificates")
    b = train_lgb(
        X[tr],
        y[tr],
        X[va],
        y[va],
        {
            "objective": "regression",
            "metric": "l1",
            "learning_rate": 0.08,
            "monotone_constraints": mono,
            "monotone_constraints_method": "advanced",
        },
        rounds=4000,
    )

    base = c[tr].groupby(["age_band", "property_type"])["sap_score"].median()
    glob = float(c.loc[tr, "sap_score"].median())

    def baseline(mask):
        return (
            c[mask]
            .set_index(["age_band", "property_type"])
            .index.map(base)
            .to_numpy(dtype=float, na_value=glob)
        )

    metrics = {}
    for name, m in (("val", va), ("test", te)):
        p = b.predict(X[m], num_iteration=b.best_iteration)
        pb = baseline(m)
        metrics[name] = {
            "model": {
                **regression_metrics(y[m], p, c.loc[m, "property_id"].to_numpy()),
                **band_metrics(y[m], p),
            },
            "baseline_median_by_age_type": {
                **regression_metrics(y[m], pb, c.loc[m, "property_id"].to_numpy()),
                **band_metrics(y[m], pb),
            },
        }
        print(
            f"  {name}: MAE {metrics[name]['model']['mae']:.2f} (baseline "
            f"{metrics[name]['baseline_median_by_age_type']['mae']:.2f}), "
            f"band acc {metrics[name]['model']['band_accuracy']:.3f}, within-1 "
            f"{metrics[name]['model']['within_one_band']:.3f}"
        )
        if name == "test":
            pd.DataFrame(
                {
                    "cert_id": c.loc[m, "cert_id"],
                    "property_id": c.loc[m, "property_id"],
                    "sap_true": y[m],
                    "sap_pred": p.round(2),
                    "band_true": c.loc[m, "energy_rating"],
                    "band_pred": sap_to_band(p),
                    "sap_baseline": pb,
                }
            ).to_csv(PRED / "rating_test.csv.gz", index=False)

    # model-implied retrofit SAP gains on test homes vs real repeat-EPC gains
    latest = (
        c[te].sort_values("lodgement_date").drop_duplicates("property_id", keep="last").reset_index(drop=True)
    )
    feas = feasible_set(latest)
    p0 = b.predict(F.rating_features(latest), num_iteration=b.best_iteration)
    real = pd.read_csv(REPORTS / "retrofit_history_summary.csv", index_col=0)[
        "single_change_median_delta_sap"
    ]
    rows = []
    for r in F.RETROFITS:
        m = feas[r].to_numpy()
        if m.sum() < 50:
            continue
        after = apply_retrofits(latest[m], frozenset([r]))
        d = b.predict(F.rating_features(after), num_iteration=b.best_iteration) - p0[m]
        rows.append(
            {
                "retrofit": r,
                "homes": int(m.sum()),
                "model_median_delta_sap": float(np.median(d)),
                "model_share_negative": float((d < -1e-6).mean()),
                "real_repeat_epc_median_delta_sap": float(real.get(r, np.nan)),
            }
        )
    dsap = pd.DataFrame(rows).set_index("retrofit")
    dsap.round(3).to_csv(REPORTS / "rating_model_delta_sap.csv")
    print(dsap.round(2).to_string())
    metrics["delta_sap_check"] = dsap.round(3).reset_index().to_dict("records")

    imp = pd.Series(b.feature_importance("gain"), index=X.columns).sort_values(ascending=False)
    save_model(
        "rating",
        b,
        X,
        mono,
        metrics,
        {
            "target": "sap_score",
            "band_thresholds": {b_: lo for lo, b_ in BANDS},
            "feature_importance_gain": (imp / imp.sum()).round(4).to_dict(),
        },
    )
    print("saved models/rating")


if __name__ == "__main__":
    main()
