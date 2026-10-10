"""M2: retrofit relevance model on REAL EPC assessor recommendations (README P3.3).

One LightGBM binary classifier per retrofit, trained only on certificates where the retrofit is
rule-feasible: P(an EPC assessor would recommend r | home). Feasibility itself is never ML.
Heat pump: EPC software only started recommending heat pumps with RdSAP 10 (certificates lodged from 2025);
earlier certificates could never carry a positive label. So the heat-pump model is trained and evaluated
on 2025+ certificates only (1,019 positives, almost all electrically heated homes).

Training rows are subsampled to <= 1M per retrofit (memory/time); val/test are evaluated in full.
Metrics per retrofit: ROC-AUC, PR-AUC, precision/recall/F1 at the val-tuned threshold (max F1).
Ranking per certificate (NDCG@3 vs the assessor's own order) on feasible retrofits.
Baselines: "recommend all feasible" and "popularity by property type" (train recommendation rate).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score

from greenhome.ml import features as F
from training.common import PRED, PROCESSED, REPORTS, SEED, save_model, splits, train_lgb

MAX_TRAIN = 1_000_000
LABEL_VALID_FROM = {"air_source_heat_pump": "2025-01-01"}   # label only possible from RdSAP 10 onwards


def ndcg_at_k(df: pd.DataFrame, score: str, k: int = 3) -> float:
    """Graded relevance from the assessor order (first recommendation most relevant)."""
    df = df.copy()
    df["rel"] = np.where(df["assessor_recommended"], 1.0 / df["assessor_order"].astype(float).clip(lower=1), 0.0)
    df["rank"] = df.groupby("cert_id")[score].rank(ascending=False, method="first")
    df["ideal"] = df.groupby("cert_id")["rel"].rank(ascending=False, method="first")
    disc = lambda r: 1 / np.log2(r + 1)
    dcg = (df["rel"] * disc(df["rank"]) * (df["rank"] <= k)).groupby(df["cert_id"]).sum()
    idcg = (df["rel"] * disc(df["ideal"]) * (df["ideal"] <= k)).groupby(df["cert_id"]).sum()
    ok = idcg > 0
    return float((dcg[ok] / idcg[ok]).mean())


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated retrofits to (re)train")
    only = {x for x in ap.parse_args().only.split(",") if x}
    lab = pd.read_parquet(PROCESSED / "labels" / "recommender_labels.parquet")
    lab = lab[lab["rule_feasible"]]
    certs = pd.read_parquet(PROCESSED / "epc_certificates_model.parquet").set_index("cert_id")
    sp = splits().set_index("property_id")["split"]
    lab["split"] = lab["property_id"].map(sp)
    rng = np.random.default_rng(SEED)

    metrics, scored = {}, []
    retrofits = [r for r in F.RETROFITS if lab.loc[lab.retrofit == r, "assessor_recommended"].sum() > 0]
    print("M2 recommender: models for", retrofits, "| no positives (no model):",
          [r for r in F.RETROFITS if r not in retrofits])
    if only:
        retrofits = [r for r in retrofits if r in only]
    for r in retrofits:
        L = lab[lab.retrofit == r]
        if r in LABEL_VALID_FROM:
            dates = certs.loc[L.cert_id, "lodgement_date"].to_numpy()
            L = L[dates >= np.datetime64(LABEL_VALID_FROM[r])]
        tr = L[L.split == "train"]
        if len(tr) > MAX_TRAIN:
            tr = tr.iloc[np.sort(rng.choice(len(tr), MAX_TRAIN, replace=False))]
        va, te = L[L.split == "val"], L[L.split == "test"]
        Xtr, Xva, Xte = (F.recommender_features(certs.loc[x.cert_id].reset_index()) for x in (tr, va, te))
        ytr, yva, yte = (x["assessor_recommended"].astype(int).to_numpy() for x in (tr, va, te))
        print(f" {r}: train {len(tr):,} (pos {ytr.mean():.3f}) / val {len(va):,} / test {len(te):,}")
        b = train_lgb(Xtr, ytr, Xva, yva, {"objective": "binary", "metric": "auc", "min_data_in_leaf": 200},
                      rounds=2000)
        pva, pte = b.predict(Xva, num_iteration=b.best_iteration), b.predict(Xte, num_iteration=b.best_iteration)
        grid = np.linspace(0.05, 0.95, 91)
        thr = float(grid[np.argmax([f1_score(yva, pva >= t) for t in grid])])
        # popularity baseline: train recommendation rate by property type
        pop = tr.assign(pt=certs.loc[tr.cert_id, "property_type"].to_numpy()).groupby("pt")["assessor_recommended"].mean()
        pop_te = certs.loc[te.cert_id, "property_type"].map(pop).fillna(ytr.mean()).to_numpy()
        m = {"threshold_val_maxF1": thr, "positive_rate_test": float(yte.mean()),
             "roc_auc": float(roc_auc_score(yte, pte)), "pr_auc": float(average_precision_score(yte, pte)),
             "precision": float(precision_score(yte, pte >= thr)), "recall": float(recall_score(yte, pte >= thr)),
             "f1": float(f1_score(yte, pte >= thr)),
             "baseline_recommend_all_feasible": {"precision": float(yte.mean()), "recall": 1.0,
                                                 "f1": float(2 * yte.mean() / (1 + yte.mean()))},
             "baseline_popularity_by_type": {"roc_auc": float(roc_auc_score(yte, pop_te)),
                                             "pr_auc": float(average_precision_score(yte, pop_te))}}
        metrics[r] = m
        print(f"   AUC {m['roc_auc']:.3f} (popularity {m['baseline_popularity_by_type']['roc_auc']:.3f}) | "
              f"F1 {m['f1']:.3f} vs recommend-all {m['baseline_recommend_all_feasible']['f1']:.3f}")
        te_out = te[["cert_id", "property_id", "retrofit", "assessor_recommended", "assessor_order"]].copy()
        te_out["p"], te_out["p_popularity"] = pte, pop_te
        scored.append(te_out)
        imp = pd.Series(b.feature_importance("gain"), index=Xtr.columns)
        save_model(f"recommender/{r}", b, Xtr, [0] * Xtr.shape[1], m,
                   {"target": "assessor_recommended (EPC recommendations)", "trained_on": "rule-feasible certificates",
                    "feature_importance_gain": (imp / imp.sum()).round(4).sort_values(ascending=False).to_dict()})

    if only:
        print("partial run (--only): NDCG/summary tables not rewritten")
        return
    S = pd.concat(scored)
    nd = {"model": ndcg_at_k(S, "p"), "popularity_by_type": ndcg_at_k(S, "p_popularity"),
          "random_order": ndcg_at_k(S.assign(rnd=rng.random(len(S))), "rnd")}
    metrics["ndcg@3_test"] = nd
    print("NDCG@3 (test, vs assessor order):", {k: round(v, 3) for k, v in nd.items()})
    S["predicted_suitability_input"] = S["p"].round(4)
    S.to_csv(PRED / "recommender_test.csv", index=False)
    tab = pd.DataFrame({r: {k: v for k, v in m.items() if not isinstance(v, dict)} for r, m in metrics.items()
                        if r in retrofits}).T
    tab["popularity_auc"] = [metrics[r]["baseline_popularity_by_type"]["roc_auc"] for r in tab.index]
    tab["recommend_all_f1"] = [metrics[r]["baseline_recommend_all_feasible"]["f1"] for r in tab.index]
    tab.round(3).to_csv(REPORTS / "recommender_metrics.csv")
    (REPORTS / "recommender_ndcg.csv").write_text(pd.Series(nd).round(4).to_csv())


if __name__ == "__main__":
    main()
