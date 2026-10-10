"""State changes from retrofits (README P2.3, §7.1 "State changes from retrofits").

The ONLY place a home's features change after retrofits; the simulator, training and orchestrator all use it.
Idempotent and order-independent: each retrofit sets its own fields to a fixed or "at least" value.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from greenhome.config import get_config
from greenhome.contracts import (
    Glazing,
    HeatingSystem,
    HomeInput,
    MainFuel,
    Renewables,
    Retrofit,
    RoofInsulation,
    SmartControls,
    WallInsulation,
)

_RETROFITS = {r.value for r in Retrofit}


def apply_retrofits(home: HomeInput, package: Iterable[str]) -> HomeInput:
    """New HomeInput with the package installed; `home` (and its energy block) is left untouched."""
    pkg = {str(r) for r in package}
    if unknown := pkg - _RETROFITS:
        raise ValueError(f"unknown retrofit(s): {sorted(unknown)}")
    update: dict[str, Any] = {}
    if Retrofit.loft_insulation.value in pkg:
        update["roof_insulation"] = RoofInsulation.full.value
    if pkg & {Retrofit.cavity_wall_insulation.value, Retrofit.solid_wall_insulation.value}:
        update["wall_insulation"] = WallInsulation.full.value
    if Retrofit.double_glazing.value in pkg and home.glazing != Glazing.triple:
        update["glazing"] = Glazing.double.value
    if Retrofit.air_source_heat_pump.value in pkg:
        update["heating_system"] = HeatingSystem.heat_pump.value
        update["main_fuel"] = MainFuel.electricity.value
    if Retrofit.solar_pv.value in pkg and home.renewables != Renewables.solar_pv_battery:
        update["renewables"] = Renewables.solar_pv.value
    if Retrofit.smart_thermostat.value in pkg:
        order = get_config().quality_order("smart_controls")
        update["smart_controls"] = max(
            (home.smart_controls, SmartControls.smart_thermostat.value),
            key=lambda v: -1 if v is None else order.index(v),  # None (unknown) counts as worst
        )
    return home.model_copy(update=update, deep=True)
