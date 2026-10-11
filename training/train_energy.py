"""M1: post-retrofit energy per fuel (BUILD_GUIDE P3.2), trained on simulator labels with hidden factors.

Why ML on simulated labels is not circular: the simulator uses hidden household factors (setpoint,
occupancy, appliance use, exposure, true SCOP, PV orientation/self-use, per-home effect draws) that a
deployed model cannot see. The model learns the EXPECTED outcome from observable inputs only.

Targets (two LightGBM regressors), each relative to the SAME fuel's own baseline:
  electricity  y = elec_after / elec_before          (a loft retrofit -> ratio ~1.0 exactly)
  gas          y = gas_after / gas_before, trained only on homes with gas (gas-free homes stay 0)
The gas model never sees the solar flag (solar cannot change gas use): F.mask_for_fuel.
An earlier version normalised both fuels by the combined baseline; errors then leaked across fuels
(loft "raised" electricity, solar "cut" gas). Monotone: gas -1 on every package flag; electricity -1 on
fabric/controls/solar flags; heat-pump flag free for electricity (it raises electricity in a gas home but
lowers it in a storage-heater home). Predictions clipped >= 0.

Baselines (BUILD_GUIDE P3.2):
  B1 catalogue rule   per-fuel multiplicative midpoints (space heating ~70% of gas; HP at SCOP 2.8)
  B2 mean % by type   mean single-retrofit fractional change per fuel by property type (train),
                      multiplied across the package
  B3 additive singles the MODEL's own single-retrofit savings added up (shows why interactions matter)
Also: NEED observed-savings (performance gap) comparison for loft and cavity insulation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

from greenhome.ml import features as F
from training.common import PRED, PROCESSED, REPORTS, ROOT, bootstrap_ci, save_model, splits, train_lgb

CAT = {r["retrofit"]: r for r in yaml.safe_load((ROOT / "config" / "retrofit_catalogue.yaml").read_text())}
FLAGS = [f"r_{r}" for r in F.RETROFITS]


def load() -> pd.DataFrame:
    e = pd.read_parquet(PROCESSED / "labels" / "energy_scenarios.parquet")
    props = pd.read_parquet(PROCESSED / "properties.parquet")
    return e.merge(props, on="property_id").merge(splits(), on="property_id")


def catalogue_rule(d: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """B1: documented catalogue midpoints applied per fuel, multiplicatively."""
    gas, el = d["gas_before"].to_numpy().copy(), d["elec_before"].to_numpy().copy()
    heat_share = 0.70
    for r in [
        "loft_insulation",
        "cavity_wall_insulation",
        "solid_wall_insulation",
        "double_glazing",
        "smart_thermostat",
    ]:
        mids = [np.mean(v) for v in CAT[r]["effect_range_frac"].values()]
        f = np.where(d[f"r_{r}"], 1 - heat_share * float(np.mean(mids)), 1.0)
        gas_heated = d["heating_system"].str.startswith("gas").to_numpy()
        gas = np.where(gas_heated, gas * f, gas)
        el = np.where(
            ~gas_heated & d["heating_system"].ne("heat_pump").to_numpy(), el * (1 - (1 - f) * 0.6), el
        )
    hp = d["r_air_source_heat_pump"].to_numpy()
    moved = np.where(d["heating_system"].str.startswith("gas"), gas * 0.95 * 0.85, 0.0)
    el = np.where(hp, el + moved / 2.8, el)
    gas = np.where(hp, gas - moved, gas)
    pv = d["r_solar_pv"].to_numpy()
    el = np.where(pv, el * (1 - 0.275), el)
    return np.clip(el, 0, None), np.clip(gas, 0, None)


def main() -> None:
    d = load()
    X = F.energy_features(d, d["elec_before"], d["gas_before"], d[FLAGS].rename(columns=lambda c: c))
    tr, va, te = (d["split"] == s for s in ("train", "val", "test"))
    print(f"M1 energy: train {tr.sum():,} / val {va.sum():,} / test {te.sum():,} (home x package) rows")

    specs = {"gas": {f: -1 for f in FLAGS}, "elec": {f: -1 for f in FLAGS if f != "r_air_source_heat_pump"}}
    base = {"elec": d["elec_before"].to_numpy(), "gas": d["gas_before"].to_numpy()}
    models, preds = {}, {}
    Xf = {"elec": X, "gas": F.mask_for_fuel(X, "gas")}
    for fuel, col in (("elec", "elec_after"), ("gas", "gas_after")):
        has = base[fuel] > 1.0  # gas model: homes with a gas baseline only
        y = np.where(has, d[col].to_numpy() / np.maximum(base[fuel], 1.0), 0.0)
        X = Xf[fuel]
        mono = F.monotone_constraints(list(X.columns), specs[fuel])
        models[fuel] = train_lgb(
            X[tr & has],
            y[tr & has],
            X[va & has],
            y[va & has],
            {
                "objective": "regression",
                "metric": "l1",
                "min_data_in_leaf": 100,
                "monotone_constraints": mono,
                "monotone_constraints_method": "advanced",
            },
        )
        ratio = np.clip(models[fuel].predict(X, num_iteration=models[fuel].best_iteration), 0, None)
        # no retrofit relevant to this fuel in the package -> baseline exactly (same rule as inference)
        relevant = d[[f for f in FLAGS if f not in F.FUEL_IRRELEVANT[fuel]]].any(axis=1).to_numpy()
        ratio = np.where(relevant, ratio, 1.0)
        preds[fuel] = np.where(has, ratio * base[fuel], 0.0)

    # baselines
    b1_el, b1_gas = catalogue_rule(d)
    singles = d[d[FLAGS].sum(axis=1) == 1].copy()
    singles["which"] = singles[FLAGS].idxmax(axis=1)
    s_tr = singles[singles["split"] == "train"]
    rat = (
        s_tr.assign(
            re=s_tr.elec_after / s_tr.elec_before.clip(lower=1),
            rg=s_tr.gas_after / s_tr.gas_before.clip(lower=1),
        )
        .groupby(["property_type", "which"])[["re", "rg"]]
        .mean()
    )
    b2_el, b2_gas = d["elec_before"].to_numpy().copy(), d["gas_before"].to_numpy().copy()
    for f in FLAGS:
        m = d[f].to_numpy()
        key = pd.MultiIndex.from_arrays([d["property_type"], [f] * len(d)])
        b2_el = np.where(m, b2_el * rat["re"].reindex(key).fillna(1).to_numpy(), b2_el)
        b2_gas = np.where(m, b2_gas * rat["rg"].reindex(key).fillna(1).to_numpy(), b2_gas)
    # B3: additive model singles
    single_pred = {}
    for f in FLAGS:
        single_pred[f] = {}
        for fu in ("elec", "gas"):
            Xs = Xf[fu].copy()
            Xs[FLAGS] = 0.0
            Xs[f] = 1.0
            Xs = F.mask_for_fuel(Xs, fu)
            r_ = np.clip(models[fu].predict(Xs, num_iteration=models[fu].best_iteration), 0, None)
            r_ = r_ if f not in F.FUEL_IRRELEVANT[fu] else np.ones_like(r_)
            single_pred[f][fu] = np.where(base[fu] > 1.0, r_ * base[fu], 0.0)
    b3_el = d["elec_before"].to_numpy() - sum(
        np.where(d[f], d["elec_before"] - single_pred[f]["elec"], 0) for f in FLAGS
    )
    b3_gas = d["gas_before"].to_numpy() - sum(
        np.where(d[f], d["gas_before"] - single_pred[f]["gas"], 0) for f in FLAGS
    )

    true_s = {"elec": d["elec_before"] - d["elec_after"], "gas": d["gas_before"] - d["gas_after"]}
    cands = {
        "model": (preds["elec"], preds["gas"]),
        "B1_catalogue_rule": (b1_el, b1_gas),
        "B2_mean_pct_by_type": (b2_el, b2_gas),
        "B3_additive_singles": (b3_el, b3_gas),
    }
    multi = d[FLAGS].sum(axis=1).to_numpy() >= 2
    metrics, rows = {}, []
    for split_name, m in (("val", va.to_numpy()), ("test", te.to_numpy())):
        metrics[split_name] = {}
        g = d.loc[m, "property_id"].to_numpy()
        for name, (pe, pg) in cands.items():
            se, sg = d["elec_before"].to_numpy() - pe, d["gas_before"].to_numpy() - pg
            ae_e, ae_g = np.abs(se - true_s["elec"].to_numpy())[m], np.abs(sg - true_s["gas"].to_numpy())[m]
            net_t = (true_s["elec"] + true_s["gas"]).to_numpy()[m]
            net_p = (se + sg)[m]
            hp = d["r_air_source_heat_pump"].to_numpy()[m]
            r = {
                "mae_saving_elec_kwh": float(ae_e.mean()),
                "mae_saving_gas_kwh": float(ae_g.mean()),
                "mae_saving_net_kwh": float(np.abs(net_p - net_t).mean()),
                "mape_net_saving_pct": float(
                    np.median(np.abs(net_p - net_t) / np.maximum(np.abs(net_t), 100)) * 100
                ),
                "mae_net_multi_retrofit_packages": float(np.abs(net_p - net_t)[multi[m]].mean()),
                "elec_increase_sign_accuracy_hp": float(
                    ((se[m][hp] < 0) == (true_s["elec"].to_numpy()[m][hp] < 0)).mean()
                ),
                "mae_saving_net_ci95": bootstrap_ci(
                    g, {"ae": np.abs(net_p - net_t), "n": np.ones(len(g))}, lambda s: s["ae"] / s["n"]
                )
                if name == "model"
                else None,
            }
            metrics[split_name][name] = r
            rows.append(
                {
                    "split": split_name,
                    "method": name,
                    **{k: v for k, v in r.items() if k != "mae_saving_net_ci95"},
                }
            )
    rep = pd.DataFrame(rows).set_index(["split", "method"]).round(1)
    rep.to_csv(REPORTS / "energy_model_metrics.csv")
    print(rep.to_string())

    # performance gap: model median gas saving share for single loft/cavity vs NEED observed
    gap = []
    for r in ["loft_insulation", "cavity_wall_insulation"]:
        s = singles[
            (singles["which"] == f"r_{r}")
            & (singles["split"] == "test")
            & singles["heating_system"].str.startswith("gas")
        ]
        idx = s.index
        frac = 1 - preds["gas"][idx] / s["gas_before"].to_numpy()
        obs = CAT[r]["observed_need"]["gas_saving_frac"]
        gap.append(
            {
                "retrofit": r,
                "model_median_gas_saving_pct": float(np.median(frac) * 100),
                "simulator_median_gas_saving_pct": float(np.median(1 - s.gas_after / s.gas_before) * 100),
                "NEED_observed_gas_saving_pct": f"{obs[0] * 100:.1f}-{obs[1] * 100:.1f}",
            }
        )
    gap = pd.DataFrame(gap).set_index("retrofit")
    gap.round(1).to_csv(REPORTS / "energy_performance_gap.csv")
    print(gap.round(1).to_string())
    metrics["performance_gap"] = gap.round(2).reset_index().to_dict("records")

    out = d.loc[
        te, ["property_id", "package_id", "package", "elec_before", "gas_before", "elec_after", "gas_after"]
    ].copy()
    out["elec_after_pred"], out["gas_after_pred"] = (
        preds["elec"][te.to_numpy()].round(1),
        preds["gas"][te.to_numpy()].round(1),
    )
    out.rename(columns={"elec_after": "elec_after_ref", "gas_after": "gas_after_ref"}).to_csv(
        PRED / "energy_test.csv.gz", index=False
    )
    for fuel in ("elec", "gas"):
        mono = F.monotone_constraints(list(Xf[fuel].columns), specs[fuel])
        save_model(
            f"energy_{fuel}",
            models[fuel],
            Xf[fuel],
            mono,
            metrics if fuel == "elec" else {"see": "energy_elec"},
            {
                "target": f"{fuel}_after / {fuel}_before",
                "inference": f"pred * {fuel}_before (0 if no {fuel} baseline), clip >= 0",
            },
        )
    print("saved models/energy_elec, models/energy_gas")


if __name__ == "__main__":
    main()
