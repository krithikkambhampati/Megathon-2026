"""Calibrate the physics model so synthetic consumption matches real NEED statistics (BUILD_GUIDE P1.7).

Targets: NEED multiple-attributes table, latest year (2024), medians and quartiles per cell.
Prebound (by EPC band): real poorly-rated homes use far less gas than their rating implies (NEED: F/G
homes use no more gas per m2 than D/E). Occupants heat fewer rooms / to lower temperatures and
RdSAP overstates old-fabric heat loss (Sunikka-Blank & Galvin 2012, "prebound effect"). We fit a
per-band space-heat multiplier jointly with the cell factors (iterative raking) so our median gas per
m2 by band matches NEED Table 14.2 (houses). Without it, savings for F/G homes would be overstated.

Cells (coarse enough that every cell has plenty of homes in both NEED and our sample):
  gas  : property_type x age_group     over gas-heated homes        -> multiplier cal_sh[cell]
  elec : property_type x bedrooms_grp  over gas-heated homes        -> multiplier cal_el[cell]
         (gas-heated, standard tariff, so NEED electricity is appliances/lighting, as in our cal_el term)
NEED's cell targets are sample-size-weighted means of its finer cell medians/quartiles (documented
approximation). We iterate multiplicative updates until each cell's simulated median is within 2%
of target, and report the fit plus how well our dispersion (IQR) matches NEED.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from data_pipeline import physics as ph

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "processed" / "reference"

AGE_GROUP_OURS = {
    "pre_1900": "pre_1945",
    "1900_1929": "pre_1945",
    "1930_1949": "pre_1945",
    "1950_1966": "1945_1982",
    "1967_1982": "1945_1982",
    "1983_1995": "post_1982",
    "1996_2006": "post_1982",
    "2007_onwards": "post_1982",
}
AGE_GROUP_NEED = {
    "Pre 1919": "pre_1945",
    "1919 - 1944": "pre_1945",
    "1945 - 1964": "1945_1982",
    "1965 - 1982": "1945_1982",
    "1983 - 1992": "post_1982",
    "1993 - 1999": "post_1982",
    "2000 - 2011": "post_1982",
    "2012 onwards": "post_1982",
}
PTYPE_GROUP = {
    "detached": "detached",
    "semi_detached": "semi_detached",
    "terraced": "terraced",
    "bungalow": "bungalow",
    "flat": "flat",
    "maisonette": "flat",
}


def beds_group(b: pd.Series) -> pd.Series:
    return pd.cut(b.fillna(2), [-1, 1, 2, 3, 99], labels=["1", "2", "3", "4+"]).astype(str)


def need_targets() -> tuple[pd.DataFrame, pd.DataFrame]:
    m = pd.read_parquet(REF / "need_multi.parquet")
    m = m[(m["year"] == m["year"].max()) & m["property_type"].notna()].copy()
    m["ptype"] = m["property_type"].map(PTYPE_GROUP)
    m["age_group"] = m["need_property_age"].map(AGE_GROUP_NEED)
    m["beds"] = beds_group(m["bedrooms_n"].astype("float"))

    def wavg(g: pd.DataFrame, cols: list[str]) -> pd.Series:
        g = g.dropna(subset=cols + ["n"])
        w = g["n"]
        return pd.Series({c: np.average(g[c], weights=w) for c in cols} | {"n_need": w.sum()})

    gas_rows = m[m["gas_present"] & (m["electricity_type"] == "Standard")]
    gas = (
        gas_rows.groupby(["ptype", "age_group"])
        .apply(wavg, cols=["gas_q25", "gas_median", "gas_q75"], include_groups=False)
        .reset_index()
    )
    el = (
        gas_rows.groupby(["ptype", "beds"])
        .apply(wavg, cols=["elec_q25", "elec_median", "elec_q75"], include_groups=False)
        .reset_index()
    )
    return gas, el


def need_band_targets() -> pd.Series:
    h = pd.read_parquet(REF / "need_headline.parquet")
    t = h[
        (h.fuel == "gas_per_m2")
        & (h.dimension == "epc_band")
        & (h.metric == "median")
        & (h.year == h.year.max())
        & h.category.isin(list("ABCDEFG"))
    ]
    return t.set_index("category")["value"]


def _fill_small_bands(k: pd.Series, fitted) -> pd.Series:
    """Bands with too few homes to fit (e.g. G) take the factor of the nearest fitted band."""
    order = list("ABCDEFG")
    fitted = [b for b in order if b in set(fitted)]
    k = k.copy()
    for b in order:
        if b not in fitted and fitted:
            nearest = min(fitted, key=lambda f: abs(order.index(f) - order.index(b)))
            k[b] = k[nearest]
    return k


def calibrate(p: pd.DataFrame, h: pd.DataFrame, iters: int = 12, tol: float = 0.02):
    """Return (cal_sh Series, cal_el Series aligned to p, fit reports, factors DataFrame)."""
    gas_t, el_t = need_targets()
    band_t = need_band_targets()
    gas_cell = p["property_type"].map(PTYPE_GROUP) + "|" + p["age_band"].map(AGE_GROUP_OURS)
    el_cell = p["property_type"].map(PTYPE_GROUP) + "|" + beds_group(p["bedrooms"])
    gas_t["cell"] = gas_t["ptype"] + "|" + gas_t["age_group"]
    el_t["cell"] = el_t["ptype"] + "|" + el_t["beds"]
    gas_target = gas_t.set_index("cell")["gas_median"]
    el_target = el_t.set_index("cell")["elec_median"]

    gas_homes = p["heating_system"].isin(["gas_boiler_condensing", "gas_boiler_old"])
    gas_houses = gas_homes & p["property_type"].isin(["detached", "semi_detached", "terraced", "bungalow"])
    band = p["energy_rating"]
    k_sh = pd.Series(1.0, index=gas_target.index)
    k_el = pd.Series(1.0, index=el_target.index)
    k_band = pd.Series(1.0, index=list("ABCDEFG"))
    for it in range(iters):
        cal_sh = gas_cell.map(k_sh).fillna(k_sh.median()) * band.map(k_band).fillna(1.0)
        cal_el = el_cell.map(k_el).fillna(k_el.median())
        fuel = ph.delivered(p, h, ph.end_uses(p, h, cal_sh, cal_el))
        sim_gas = fuel.loc[gas_homes, "gas_kwh"].groupby(gas_cell[gas_homes]).median()
        # NEED electricity for gas homes = appliances + lighting (+ any PV effect, small)
        sim_el = fuel.loc[gas_homes, "electricity_kwh"].groupby(el_cell[gas_homes]).median()
        sim_band = (
            (fuel.loc[gas_houses, "gas_kwh"] / p.loc[gas_houses, "floor_area_m2"])
            .groupby(band[gas_houses])
            .median()
        )
        n_band = band[gas_houses].value_counts()
        r_gas = (gas_target / sim_gas).dropna()
        r_el = (el_target / sim_el).dropna()
        # band factors fit only the SHAPE of NEED's gas/m2-by-band curve: that table (houses, all tariffs)
        # and the type x age table (standard tariff) are different populations, so their levels differ
        # legitimately; the type x age cells own the level.
        big = n_band[n_band >= 100].index
        r_band = (band_t / sim_band).reindex(big).dropna()
        w = n_band.reindex(r_band.index)
        r_band = r_band / np.exp(np.average(np.log(r_band), weights=w))
        worst = max((r_gas - 1).abs().max(), (r_el - 1).abs().max(), (r_band - 1).abs().max())
        print(f"iter {it}: worst cell off by {worst:.1%} (band shape worst {(r_band - 1).abs().max():.1%})")
        if worst < tol:
            break
        # gas = heat/eff + cooking: scaling space heat moves gas less than 1:1 -> damped update
        k_band.loc[r_band.index] *= r_band**1.3
        k_band = _fill_small_bands(k_band, big)
        k_sh.loc[r_gas.index] *= r_gas**1.3
        k_el.loc[r_el.index] *= r_el

    cal_sh = gas_cell.map(k_sh).fillna(k_sh.median()) * band.map(k_band).fillna(1.0)
    cal_el = el_cell.map(k_el).fillna(k_el.median())
    fuel = ph.delivered(p, h, ph.end_uses(p, h, cal_sh, cal_el))
    g = fuel.loc[gas_homes, "gas_kwh"].groupby(gas_cell[gas_homes])
    rep_gas = pd.DataFrame(
        {
            "sim_q25": g.quantile(0.25),
            "sim_median": g.median(),
            "sim_q75": g.quantile(0.75),
            "n_sim": g.size(),
        }
    ).join(gas_t.set_index("cell")[["gas_q25", "gas_median", "gas_q75", "n_need"]])
    e = fuel.loc[gas_homes, "electricity_kwh"].groupby(el_cell[gas_homes])
    rep_el = pd.DataFrame(
        {
            "sim_q25": e.quantile(0.25),
            "sim_median": e.median(),
            "sim_q75": e.quantile(0.75),
            "n_sim": e.size(),
        }
    ).join(el_t.set_index("cell")[["elec_q25", "elec_median", "elec_q75", "n_need"]])
    sb = (
        (fuel.loc[gas_houses, "gas_kwh"] / p.loc[gas_houses, "floor_area_m2"])
        .groupby(band[gas_houses])
        .median()
    )
    rep_band = pd.DataFrame(
        {
            "sim_gas_per_m2": sb,
            "need_gas_per_m2": band_t,
            "n_sim": band[gas_houses].value_counts(),
            "prebound_factor": k_band,
        }
    )
    rep_band["sim_relative_to_D"] = rep_band["sim_gas_per_m2"] / rep_band.loc["D", "sim_gas_per_m2"]
    rep_band["need_relative_to_D"] = rep_band["need_gas_per_m2"] / rep_band.loc["D", "need_gas_per_m2"]
    rep_gas.attrs["band"] = rep_band
    factors = pd.concat(
        [
            k_sh.rename("factor").to_frame().assign(kind="space_heat"),
            k_el.rename("factor").to_frame().assign(kind="appliances"),
            k_band.rename("factor").to_frame().assign(kind="prebound_band"),
        ]
    )
    return cal_sh, cal_el, rep_gas, rep_el, factors
