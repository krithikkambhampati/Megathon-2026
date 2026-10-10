"""TEMPORARY copies of Part 2's shared kernels, so Part 1 can generate labels before Part 2 lands.

README P2.3 (greenhome.core.transitions.apply_retrofits) and P2.7 (greenhome.core.feasibility.feasible_set)
are the source of truth. When greenhome/ exists, delete this module and import those instead
(README Part 1 integration hazard #5). These versions are vectorised over a DataFrame of homes.
"""
from __future__ import annotations

import pandas as pd

SMART_ORDER = ["none", "timer_only", "programmer_thermostat", "programmer_thermostat_trvs",
               "smart_thermostat", "smart_zoned"]


def apply_retrofits(p: pd.DataFrame, package: frozenset[str]) -> pd.DataFrame:
    """Post-retrofit feature state. Idempotent and order-independent."""
    q = p.copy()
    if "loft_insulation" in package:
        q.loc[q["roof_type"].ne("dwelling_above"), "roof_insulation"] = "full"
    if "cavity_wall_insulation" in package:
        q.loc[q["wall_type"].eq("cavity"), "wall_insulation"] = "full"
    if "solid_wall_insulation" in package:
        q.loc[q["wall_type"].eq("solid"), "wall_insulation"] = "full"
    if "double_glazing" in package:
        q.loc[q["glazing"].isin(["single", "partial_double", "secondary"]), "glazing"] = "double"
    if "air_source_heat_pump" in package:
        q["heating_system"] = "heat_pump"
        q["main_fuel"] = "electricity"
    if "solar_pv" in package:
        q.loc[~q["renewables"].isin(["solar_pv", "solar_pv_battery"]), "renewables"] = "solar_pv"
    if "smart_thermostat" in package:
        lvl = q["smart_controls"].map({s: i for i, s in enumerate(SMART_ORDER)}).fillna(0)
        q.loc[lvl < SMART_ORDER.index("smart_thermostat"), "smart_controls"] = "smart_thermostat"
    return q


def feasible_set(p: pd.DataFrame) -> pd.DataFrame:
    """Boolean DataFrame (homes x retrofits): True if feasible or needs_survey (README P2.7)."""
    flat = p["property_type"].isin(["flat", "maisonette"])
    listed = p.get("listed_or_conservation", pd.Series(index=p.index, dtype=object)).eq("yes")
    return pd.DataFrame({
        "loft_insulation": p["roof_type"].isin(["pitched_loft", "room_in_roof"])
                           & p["roof_insulation"].isin(["none", "low", "medium"]),
        "cavity_wall_insulation": p["wall_type"].eq("cavity") & p["wall_insulation"].isin(["none", "partial"]),
        "solid_wall_insulation": p["wall_type"].eq("solid") & p["wall_insulation"].isin(["none", "partial"]),
        "double_glazing": p["glazing"].isin(["single", "partial_double", "secondary"]) & ~listed,
        "smart_thermostat": p["smart_controls"].isin(SMART_ORDER[:4])
                            & ~p["heating_system"].eq("electric_direct") & p["heating_system"].notna(),
        "air_source_heat_pump": p["heating_system"].notna() & p["heating_system"].ne("heat_pump"),
        "solar_pv": ~p["renewables"].isin(["solar_pv", "solar_pv_battery"]) & ~flat
                    & p["roof_type"].ne("dwelling_above"),
    }, index=p.index)
