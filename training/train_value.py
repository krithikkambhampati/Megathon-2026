"""M3: hedonic property value model on REAL Land Registry sales (README P3.4).

Rows: sales with the EPC certificate valid at sale (no look-ahead); features as at that certificate.
Features: HomeInput-available fields only (region, not local authority) + rating at sale + market
conditions (months since 2015-01 and the regional UK HPI at the sale month). Target: log(price).
Ensemble: 20 LightGBM models, each on a bootstrap resample of TRAIN PROPERTIES (all sales of a drawn
property are kept together); early stopping on val. Monotone +1 on rating (a better band never lowers
predicted value, other things equal).

Uplift for a rating change r0 -> r1 at as_of: per member, exp(f(x, r1) - f(x, r0)) - 1; the range is the
P10-P90 across members (Part 2 widens it to >= +-0.5 pp and labels it indicative, not causal).

Evaluation (val + test): MAPE/MAE of price vs baselines (regional x type median GBP/m2 HPI-indexed;
flat literature-style uplift); REAL-WORLD uplift check on repeat sales whose EPC band changed between
sales (observed HPI-adjusted log change vs model-implied change); OLS hedonic check with property-
clustered standard errors (band coefficients, transparency).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from greenhome.ml import features as F
from training.common import PRED, PROCESSED, REPORTS, SEED, save_model, splits, train_lgb

N_MODELS = 20
REGION_HPI = {
    "north_east": "E12000001",
    "north_west": "E12000002",
    "yorkshire_humber": "E12000003",
    "east_midlands": "E12000004",
    "west_midlands": "E12000005",
    "east_of_england": "E12000006",
    "london": "E12000007",
    "south_east": "E12000008",
    "south_west": "E12000009",
    "wales": "W92000004",
}
BANDS = list("GFEDCBA")


def month_index(month: pd.Series) -> pd.Series:
    p = pd.PeriodIndex(month, freq="M")
    return pd.Series((p.year - 2015) * 12 + (p.month - 1), index=month.index).astype(float)


def hpi_region(region: pd.Series, month: pd.Series) -> pd.Series:
    h = pd.read_parquet(PROCESSED / "reference" / "hpi_monthly.parquet")
    h = h[h.ppd_property_type == "ALL"].set_index(["area_code", "month"])["index"]
    keys = list(zip(region.map(REGION_HPI), month, strict=False))
    return pd.Series(h.reindex(keys).to_numpy(), index=region.index)


def load() -> pd.DataFrame:
    s = pd.read_parquet(PROCESSED / "sales_history.parquet").dropna(subset=["cert_id_at_sale"])
    c = pd.read_parquet(PROCESSED / "epc_certificates_model.parquet").drop(columns=["property_id"])
    d = s.merge(c, left_on="cert_id_at_sale", right_on="cert_id").merge(splits(), on="property_id")
    d["month"] = pd.to_datetime(d["sale_date"]).dt.strftime("%Y-%m")
    d["month_index"] = month_index(d["month"])
    d["hpi"] = hpi_region(d["region"], d["month"])
    return d.dropna(subset=["hpi"]).reset_index(drop=True)


def X_of(d: pd.DataFrame, rating: pd.Series | None = None) -> pd.DataFrame:
    return F.value_features(
        d, d["energy_rating_at_sale"] if rating is None else rating, d["month_index"], d["hpi"]
    )


def ens_predict(models, X) -> np.ndarray:
    return np.vstack([m.predict(X, num_iteration=m.best_iteration) for m in models])  # (members, rows)


def load_saved() -> list:
    import json

    from training.common import MODELS

    man = json.loads((MODELS / "value" / "manifest.json").read_text())
    from greenhome.ml.inference import _booster

    return [_booster(MODELS / "value" / f) for f in man["model_files"]]


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-only", action="store_true", help="load saved members; re-run evaluation only")
    eval_only = ap.parse_args().eval_only
    d = load()
    y = np.log(d["price_gbp"].to_numpy(float))
    X = X_of(d)
    tr, va, te = (d["split"] == s for s in ("train", "val", "test"))
    print(f"M3 value: train {tr.sum():,} / val {va.sum():,} / test {te.sum():,} sales")
    mono = F.monotone_constraints(list(X.columns), {"rating_ord": 1})
    params = {
        "objective": "regression",
        "metric": "l1",
        "num_leaves": 127,
        "min_data_in_leaf": 100,
        "monotone_constraints": mono,
        "monotone_constraints_method": "advanced",
    }
    extra = {
        "target": "log(price_gbp)",
        "ensemble": f"{N_MODELS} property-bootstrap members",
        "region_hpi_codes": REGION_HPI,
        "month_index_origin": "2015-01",
        "uplift": "per member exp(f(x,r1)-f(x,r0))-1; range = P10-P90 across members",
        "caveat": "associational, indicative; not a causal effect of retrofits",
    }
    if eval_only:
        models = load_saved()
        print(f" loaded {len(models)} saved members")
    else:
        rng = np.random.default_rng(SEED)
        tr_props = d.loc[tr, "property_id"].unique()
        by_prop = d[tr].groupby("property_id").indices
        tr_idx_all = np.flatnonzero(tr.to_numpy())
        models = []
        for k in range(N_MODELS):
            draw = rng.choice(tr_props, len(tr_props), replace=True)
            rows = tr_idx_all[np.concatenate([by_prop[p] for p in draw])]
            print(f" member {k + 1}/{N_MODELS}:", end="")
            models.append(
                train_lgb(X.iloc[rows], y[rows], X[va], y[va], {**params, "seed": SEED + k}, rounds=2000)
            )
        # save immediately: an evaluation failure must never lose trained members
        save_model("value", models, X, mono, {"status": "trained; evaluation pending"}, extra)
        export_hpi()
        print(" saved models/value (evaluation pending)")

    # baseline: regional x type median GBP/m2 (train), HPI-indexed to the sale month
    ref_hpi = d.loc[tr, "hpi"]
    per_m2 = (
        (d.loc[tr, "price_gbp"] / d.loc[tr, "floor_area_m2"] / ref_hpi)
        .groupby([d.loc[tr, "region"], d.loc[tr, "property_type"]])
        .median()
    )

    metrics = {}
    for name, m in (("val", va), ("test", te)):
        P = ens_predict(models, X[m])
        pred = np.exp(np.median(P, axis=0))
        truth = d.loc[m, "price_gbp"].to_numpy(float)
        key = pd.MultiIndex.from_arrays([d.loc[m, "region"], d.loc[m, "property_type"]])
        base = (
            per_m2.reindex(key).to_numpy() * d.loc[m, "floor_area_m2"].to_numpy() * d.loc[m, "hpi"].to_numpy()
        )
        ok = np.isfinite(base)
        metrics[name] = {
            "model": {
                "mape_pct": float(np.median(np.abs(pred / truth - 1)) * 100),
                "mean_ape_pct": float(np.mean(np.abs(pred / truth - 1)) * 100),
                "mae_gbp": float(np.mean(np.abs(pred - truth))),
                "n": int(m.sum()),
            },
            "baseline_region_type_gbp_per_m2": {
                "mape_pct": float(np.median(np.abs(base[ok] / truth[ok] - 1)) * 100),
                "mae_gbp": float(np.mean(np.abs(base[ok] - truth[ok]))),
            },
        }
        print(
            f"  {name}: median APE {metrics[name]['model']['mape_pct']:.1f}% "
            f"(baseline {metrics[name]['baseline_region_type_gbp_per_m2']['mape_pct']:.1f}%)"
        )
        if name == "test":
            lo, hi = np.exp(np.percentile(P, 10, axis=0)), np.exp(np.percentile(P, 90, axis=0))
            pd.DataFrame(
                {
                    "property_id": d.loc[m, "property_id"],
                    "sale_date": d.loc[m, "sale_date"],
                    "price_true": truth,
                    "price_pred": pred.round(0),
                    "price_p10": lo.round(0),
                    "price_p90": hi.round(0),
                    "price_baseline": base.round(0),
                    "rating_at_sale": d.loc[m, "energy_rating_at_sale"],
                }
            ).to_csv(PRED / "value_test.csv.gz", index=False)

    # model-implied uplift at as_of for test homes: one and two band steps up
    latest = d[te].sort_values("sale_date").drop_duplicates("property_id", keep="last").copy()
    latest["month"] = "2026-07"
    latest["month_index"] = month_index(latest["month"])
    latest["hpi"] = hpi_region(latest["region"], latest["month"])
    up_rows = []
    for steps in (1, 2):
        r0 = latest["energy_rating_at_sale"]
        ok = r0.map(BANDS.index) + steps <= 6
        L = latest[ok]
        r1 = L["energy_rating_at_sale"].map(lambda b, k=steps: BANDS[BANDS.index(b) + k])
        D = ens_predict(models, X_of(L, r1)) - ens_predict(models, X_of(L))
        upl = (np.exp(D) - 1) * 100
        up_rows.append(
            pd.DataFrame(
                {
                    "property_id": L["property_id"],
                    "rating_before": L["energy_rating_at_sale"],
                    "rating_after": r1,
                    "uplift_pct_low": np.percentile(upl, 10, axis=0),
                    "uplift_pct_mid": np.median(upl, axis=0),
                    "uplift_pct_high": np.percentile(upl, 90, axis=0),
                    "band_steps": steps,
                }
            )
        )
    up = pd.concat(up_rows)
    up.round(3).to_csv(PRED / "value_uplift_test.csv.gz", index=False)
    summ = up.groupby(["band_steps", "rating_before"])[
        ["uplift_pct_low", "uplift_pct_mid", "uplift_pct_high"]
    ].median()
    summ.round(2).to_csv(REPORTS / "value_uplift_summary.csv")
    print(summ.round(2).to_string())
    metrics["uplift_summary"] = summ.round(3).reset_index().to_dict("records")

    # REAL repeat-sales check: consecutive sales of one property where the band at sale changed
    s = d.sort_values(["property_id", "sale_date"])
    prev = s.groupby("property_id").shift(1)
    pair = (
        prev["price_gbp"].notna()
        & (prev["energy_rating_at_sale"] != s["energy_rating_at_sale"])
        & s["split"].isin(["val", "test"])
    )
    A, B = prev[pair], s[pair]
    obs = np.log(B["price_gbp"] / A["price_gbp"]) - np.log(B["hpi"] / A["hpi"])
    Dm = ens_predict(models, X_of(B)) - ens_predict(models, X_of(B, A["energy_rating_at_sale"]))
    steps = B["energy_rating_at_sale"].map(BANDS.index) - A["energy_rating_at_sale"].map(BANDS.index)
    rs = pd.DataFrame(
        {
            "band_steps": steps.to_numpy(),
            "observed_pct": (np.exp(obs.to_numpy()) - 1) * 100,
            "model_mid_pct": (np.exp(np.median(Dm, axis=0)) - 1) * 100,
            "model_lo_pct": (np.exp(np.percentile(Dm, 10, axis=0)) - 1) * 100,
            "model_hi_pct": (np.exp(np.percentile(Dm, 90, axis=0)) - 1) * 100,
        }
    )
    rs = rs[rs.band_steps.abs().between(1, 3)]
    rsum = rs.groupby("band_steps").agg(
        pairs=("observed_pct", "size"),
        observed_median_pct=("observed_pct", "median"),
        model_median_pct=("model_mid_pct", "median"),
    )
    rsum.round(2).to_csv(REPORTS / "value_repeat_sales_check.csv")
    print("repeat-sales check (HPI-adjusted, val+test properties):\n", rsum.round(2).to_string())
    metrics["repeat_sales_check"] = rsum.round(3).reset_index().to_dict("records")

    # OLS hedonic transparency check (train), band D as reference, SEs clustered by property
    o = d[tr].copy()
    o["lp"] = np.log(o["price_gbp"])
    o["year"] = pd.to_datetime(o["sale_date"]).dt.year.astype(str)
    o["band"] = pd.Categorical(o["energy_rating_at_sale"], categories=["D", "A", "B", "C", "E", "F", "G"])
    # statsmodels drops incomplete rows itself; drop them first so the cluster groups line up
    o = o.dropna(
        subset=["lp", "band", "floor_area_m2", "property_type", "age_band", "local_authority_code", "year"]
    ).reset_index(drop=True)
    fit = smf.ols(
        "lp ~ C(band) + np.log(floor_area_m2) + C(property_type) + C(age_band) + "
        "C(local_authority_code):C(year)",
        data=o,
    ).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(o["property_id"])[0]})
    coef = fit.params.filter(like="C(band)")
    ci = fit.conf_int().loc[coef.index]
    ols = pd.DataFrame(
        {
            "pct_vs_D": (np.exp(coef) - 1) * 100,
            "ci_low": (np.exp(ci[0]) - 1) * 100,
            "ci_high": (np.exp(ci[1]) - 1) * 100,
        }
    )
    ols.index = [i.split("T.")[-1].rstrip("]") for i in ols.index]
    ols.round(2).to_csv(REPORTS / "value_ols_band_coefficients.csv")
    print("OLS band premium vs D (controls: size, type, age, LA x year):\n", ols.round(2).to_string())
    metrics["ols_band_premium_vs_D_pct"] = ols.round(3).reset_index().to_dict("records")

    save_model("value", models, X, mono, metrics, extra)
    export_hpi()
    print("saved models/value (with evaluation metrics)")


def export_hpi() -> None:
    """Ship the regional HPI series with the model (inference needs it for market conditions)."""
    from training.common import MODELS

    h = pd.read_parquet(PROCESSED / "reference" / "hpi_monthly.parquet")
    h = h[(h.ppd_property_type == "ALL") & h.area_code.isin(REGION_HPI.values())]
    h[["area_code", "month", "index"]].to_csv(MODELS / "value" / "hpi_region.csv", index=False)


if __name__ == "__main__":
    main()
