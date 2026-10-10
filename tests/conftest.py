"""Shared test builders. Unit tests build CleanHome directly so each module is tested in isolation."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from greenhome.contracts import FEATURE_FIELDS, AnnualEnergy, CleanHome, HomeInput

# Keep `from conftest import …` working even if tests/ becomes a package (tests/__init__.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Tests pin the deterministic stub models; the real-model checks load greenhome.ml.registry explicitly.
os.environ.setdefault("GREENHOME_MODELS", "stub")

# The PS example home (README P1.10, P2.4 worked example).
P10001: dict[str, Any] = {
    "property_id": "P10001",
    "property_type": "semi_detached",
    "age_band": "1950_1966",
    "floor_area_m2": 85.0,
    "bedrooms": 3,
    "region": "east_midlands",
    "current_value_gbp": 350000.0,
    "energy_rating": "E",
    "roof_type": "pitched_loft",
    "roof_insulation": "low",
    "wall_type": "cavity",
    "wall_insulation": "none",
    "glazing": "single",
    "heating_system": "gas_boiler_condensing",
    "main_fuel": "mains_gas",
    "renewables": "none",
    "smart_controls": "programmer_thermostat",
    "listed_or_conservation": "no",
    "outdoor_space": "yes",
    "energy": {"annual_electricity_kwh": 4800.0, "annual_gas_kwh": 12000.0},
}


def home_input(**overrides: Any) -> HomeInput:
    """P10001 with field overrides (pass None to make a field unknown)."""
    return HomeInput.model_validate({**P10001, **overrides})


def make_clean(
    home: HomeInput | None = None,
    *,
    electricity_kwh: float | None = 4800.0,
    gas_kwh: float | None = 12000.0,
    unknown: tuple[str, ...] = (),
    sap_estimate: float | None = 45.0,
    in_savings_scope: bool = True,
) -> CleanHome:
    """CleanHome without running validation. Fields listed in `unknown` get provenance 'imputed'."""
    home = home or home_input()
    purchased = None if electricity_kwh is None or gas_kwh is None else electricity_kwh + gas_kwh
    provenance = {f: ("imputed" if f in unknown else "user") for f in FEATURE_FIELDS}
    provenance |= {"electricity_kwh": "user", "gas_kwh": "user"}
    area = home.floor_area_m2
    return CleanHome(
        home=home,
        provenance=provenance,
        energy=AnnualEnergy(
            electricity_kwh=electricity_kwh,
            gas_kwh=gas_kwh,
            purchased_kwh=purchased,
            electricity_coverage=None,
            gas_coverage=None,
            source="annual",
        ),
        intensity_kwh_m2=None if purchased is None or not area else purchased / area,
        sap_estimate=sap_estimate,
        flags=[],
        in_savings_scope=in_savings_scope,
    )


@pytest.fixture
def p10001() -> HomeInput:
    return home_input()


@pytest.fixture
def p10001_clean() -> CleanHome:
    return make_clean()
