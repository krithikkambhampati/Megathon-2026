"""Physics-lite household energy model, shared by synthetic metering and the retrofit simulator.

One home -> annual end uses (kWh/yr):
  space_heat   heat demand = floor_area * BASE_SH * form * fabric_index * hdd_factor * setpoint * cal_sh
  hot_water    heat demand = (HW_BASE + HW_PER_BED * bedrooms) * occupancy
  cooking_gas  gas homes only
  appliances   electricity for appliances + lighting = (AL_BASE + AL_PER_M2 * area) * occupancy * cal_el
  pv_gen       generation if the home has solar PV
Delivered fuel follows from the heating system efficiency (boilers) or SCOP (heat pumps), and grid
import = electricity demand - self-consumed PV.

Hidden household factors (setpoint, occupancy, true SCOP, PV orientation, self-consumption share and
the per-home retrofit effect draws) live in sim_hidden.parquet and are NEVER model features. They are
why the ML models have a real prediction problem (BUILD_GUIDE section 2.1).

All parameters are module constants or config values so the data docs can cite them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
REGIONS = yaml.safe_load((ROOT / "config" / "regions.yaml").read_text())
CATALOGUE = {
    r["retrofit"]: r for r in yaml.safe_load((ROOT / "config" / "retrofit_catalogue.yaml").read_text())
}
RETROFITS = list(CATALOGUE)

# ---- fabric index: relative heat-loss contributions (1.0 = uninsulated solid-wall pre-1900 element)
W_WALL, W_ROOF, W_GLAZ, W_VENT = 0.35, 0.25, 0.15, 0.25
U_WALL = {
    ("solid", "none"): 1.00,
    ("cavity", "none"): 0.75,
    ("timber_or_system", "none"): 0.65,
    "partial": 0.50,
    "full": 0.30,
}
U_ROOF = {"none": 1.00, "low": 0.60, "medium": 0.35, "full": 0.20}
U_GLAZ = {"single": 1.00, "partial_double": 0.75, "secondary": 0.55, "double": 0.50, "triple": 0.30}
VENT_BY_AGE = {
    "pre_1900": 1.00,
    "1900_1929": 0.95,
    "1930_1949": 0.90,
    "1950_1966": 0.85,
    "1967_1982": 0.80,
    "1983_1995": 0.72,
    "1996_2006": 0.65,
    "2007_onwards": 0.55,
}
FORM = {
    "detached": 1.15,
    "semi_detached": 1.00,
    "terraced": 0.88,
    "bungalow": 1.20,
    "flat": 0.75,
    "maisonette": 0.85,
}
BASE_SH = 190.0  # kWh heat per m2 per year for fabric_index 1.0, form 1.0, average climate (pre-calibration)
HW_BASE, HW_PER_BED = 1200.0, 450.0
COOK_GAS = (0.0, 400.0)  # uniform range, gas homes
AL_BASE, AL_PER_M2 = 1100.0, 14.0
BOILER_EFF = {"gas_boiler_condensing": 0.88, "gas_boiler_old": 0.75, "other_fuel_boiler": 0.80}
SMART_HEAT_FACTOR = {
    "none": 1.00,
    "timer_only": 0.97,
    "programmer_thermostat": 0.93,
    "programmer_thermostat_trvs": 0.91,
    "smart_thermostat": 0.87,
    "smart_zoned": 0.85,
}
PV_KWP = CATALOGUE["solar_pv"]["kwp_by_property_type"]
PV_SELF_USE_CAP, PV_SELF_USE_CAP_BATTERY = 0.35, 0.60


@dataclass(frozen=True)
class HiddenSpec:
    # spreads tuned so simulated inter-quartile ranges approach NEED's (reports/calibration_*.csv)
    setpoint_sd: float = 0.25  # heating behaviour: thermostat setpoint, hours, rooms heated
    occupancy_sd: float = 0.20  # people at home (hot water + appliances)
    appliance_sd: float = 0.42  # appliance stock/use beyond occupancy (NEED elec IQR ratio ~1.9)
    # heat-loss exposure not captured by EPC fields: a flat's floor position (ground/mid/top) and
    # number of exposed walls varies far more than a house's (end vs mid terrace)
    exposure_sd_flat: float = 0.30
    exposure_sd_house: float = 0.12


DEFAULT_SPEC = HiddenSpec()


def draw_hidden(
    props: pd.DataFrame, rng: np.random.Generator, spec: HiddenSpec = DEFAULT_SPEC
) -> pd.DataFrame:
    """One draw of unobservable household factors per property (seeded by the caller)."""
    n = len(props)
    h = pd.DataFrame(
        {
            "property_id": props["property_id"].to_numpy(),
            "setpoint_factor": rng.lognormal(0.0, spec.setpoint_sd, n),
            "occupancy_factor": rng.lognormal(0.0, spec.occupancy_sd, n),
            "appliance_factor": rng.lognormal(0.0, spec.appliance_sd, n),
            "exposure_factor": rng.lognormal(
                0.0,
                np.where(
                    props["property_type"].isin(["flat", "maisonette"]).to_numpy(),
                    spec.exposure_sd_flat,
                    spec.exposure_sd_house,
                ),
            ),
            "scop_base": rng.uniform(*CATALOGUE["air_source_heat_pump"]["scop_range"], n),
            "pv_orientation_factor": rng.uniform(0.75, 1.0, n),
            "self_consumption_frac": rng.uniform(*CATALOGUE["solar_pv"]["self_consumption_frac_range"], n),
            "cooking_gas_kwh": rng.uniform(*COOK_GAS, n),
        }
    )
    for r in RETROFITS:  # position of this home's true effect within each retrofit's documented range
        h[f"u_{r}"] = rng.uniform(0.0, 1.0, n)
    return h


def fabric_index(p: pd.DataFrame) -> pd.Series:
    wall = np.where(
        p["wall_insulation"].eq("none"),
        [U_WALL.get((t, "none"), 0.8) for t in p["wall_type"].fillna("cavity")],
        p["wall_insulation"].map(U_WALL).fillna(0.6),
    )
    roof_u = p["roof_insulation"].map(U_ROOF).fillna(0.45)
    roof = np.where(p["roof_type"].eq("dwelling_above"), 0.0, roof_u)
    glaz = p["glazing"].map(U_GLAZ).fillna(0.6)
    vent = p["age_band"].map(VENT_BY_AGE).fillna(0.8)
    return pd.Series(W_WALL * wall + W_ROOF * roof + W_GLAZ * glaz + W_VENT * vent, index=p.index)


def insulation_sub_score(p: pd.DataFrame) -> pd.Series:
    """Same mapping as config/score.yaml (BUILD_GUIDE P2.4), used for the heat-pump SCOP penalty."""
    roof = p["roof_insulation"].map({"none": 0, "low": 35, "medium": 65, "full": 100})
    wall_none = p["wall_type"].map({"solid": 0, "cavity": 20, "timber_or_system": 30}).fillna(20)
    wall = np.where(
        p["wall_insulation"].eq("none"),
        wall_none,
        p["wall_insulation"].map({"partial": 60, "full": 100}).fillna(50),
    )
    above = p["roof_type"].eq("dwelling_above") | roof.isna()
    return pd.Series(np.where(above, wall, 0.4 * roof.fillna(50) + 0.6 * wall), index=p.index)


def end_uses(
    p: pd.DataFrame, h: pd.DataFrame, cal_sh: pd.Series | float = 1.0, cal_el: pd.Series | float = 1.0
) -> pd.DataFrame:
    """Annual end-use demand per home. p and h must be row-aligned."""
    hdd = p["region"].map({r: v["hdd_factor"] for r, v in REGIONS["regions"].items()}).fillna(1.0)
    smart = p["smart_controls"].map(SMART_HEAT_FACTOR).fillna(0.95)
    space = (
        p["floor_area_m2"]
        * BASE_SH
        * p["property_type"].map(FORM).fillna(1.0)
        * fabric_index(p)
        * hdd
        * smart
        * h["setpoint_factor"].to_numpy()
        * h["exposure_factor"].to_numpy()
        * cal_sh
    )
    beds = p["bedrooms"].fillna(2).clip(1, 6)
    hot_water = (HW_BASE + HW_PER_BED * beds) * h["occupancy_factor"].to_numpy()
    appl = (
        (AL_BASE + AL_PER_M2 * p["floor_area_m2"])
        * h["occupancy_factor"].to_numpy()
        * h["appliance_factor"].to_numpy()
        * cal_el
    )
    pv_yield = p["region"].map({r: v["pv_yield_kwh_per_kwp"] for r, v in REGIONS["regions"].items()})
    kwp = p["property_type"].map(PV_KWP).fillna(0.0)
    has_pv = p["renewables"].isin(["solar_pv", "solar_pv_battery"])
    pv = np.where(has_pv, kwp * pv_yield.fillna(950) * h["pv_orientation_factor"].to_numpy(), 0.0)
    return pd.DataFrame(
        {"space_heat": space, "hot_water": hot_water, "appliances": appl, "pv_gen": pv}, index=p.index
    )


def delivered(p: pd.DataFrame, h: pd.DataFrame, eu: pd.DataFrame) -> pd.DataFrame:
    """Annual purchased fuel (grid import + gas) from end uses and the heating system."""
    heat = eu["space_heat"] + eu["hot_water"]
    hs = p["heating_system"]
    gas_heated = hs.isin(["gas_boiler_condensing", "gas_boiler_old"])
    # the gas connection is a property of the home, not of the heating system: after a heat pump the
    # meter (and cooking gas) usually remains. "gas_connected" is set from the BASELINE state.
    on_gas = gas_heated | (
        p["gas_connected"].astype(bool) if "gas_connected" in p else p["main_fuel"].eq("mains_gas")
    )
    eff = hs.map(BOILER_EFF)
    scop = h["scop_base"].to_numpy() - np.where(
        insulation_sub_score(p) < 50, CATALOGUE["air_source_heat_pump"]["scop_poor_fabric_penalty"], 0.0
    )
    gas = np.where(gas_heated, heat / eff, 0.0) + np.where(on_gas, h["cooking_gas_kwh"].to_numpy(), 0.0)
    heat_elec = np.select(
        [hs.eq("heat_pump"), hs.isin(["electric_storage", "electric_direct"])], [heat / scop, heat], 0.0
    )
    elec_demand = eu["appliances"] + heat_elec
    sc = h["self_consumption_frac"].to_numpy() + np.where(
        hs.eq("heat_pump"), CATALOGUE["solar_pv"]["self_consumption_bonus_with_heat_pump"], 0.0
    )
    battery_bonus = np.where(p["renewables"].eq("solar_pv_battery"), 0.25, 0.0)
    # cap: without storage a home can only use PV while it is generating; capped at PV_SELF_USE_CAP of
    # demand so the import cut stays within the PS2 range (20-35% of grid imports)
    cap = np.where(p["renewables"].eq("solar_pv_battery"), PV_SELF_USE_CAP_BATTERY, PV_SELF_USE_CAP)
    self_used = np.minimum(eu["pv_gen"] * np.clip(sc + battery_bonus, 0, 0.9), cap * elec_demand)
    return pd.DataFrame(
        {
            "electricity_demand_kwh": elec_demand,
            "pv_self_consumed_kwh": self_used,
            "electricity_kwh": elec_demand - self_used,  # grid import (contract meaning)
            "gas_kwh": gas,
            "out_of_scope_fuel": hs.eq("other_fuel_boiler").to_numpy(),
        },
        index=p.index,
    )
