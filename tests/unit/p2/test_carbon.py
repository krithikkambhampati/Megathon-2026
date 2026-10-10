"""Carbon formula (README P2.8 item 7)."""

from __future__ import annotations

import pytest

from greenhome.config import get_config
from greenhome.contracts import FuelSaving
from greenhome.core.carbon import compute_carbon


def saving(elec: float, gas: float) -> FuelSaving:
    return FuelSaving(electricity_kwh=elec, gas_kwh=gas, net_kwh=elec + gas)


def test_formula_uses_config_factors():
    efs = get_config().emission_factors
    ef_e, ef_g = efs["electricity"].kg_co2e_per_kwh, efs["gas"].kg_co2e_per_kwh
    c = compute_carbon(saving(1000.0, 5000.0))
    assert (c.ef_electricity, c.ef_gas) == (ef_e, ef_g)
    assert c.electricity_kg == pytest.approx(1000.0 * ef_e)
    assert c.gas_kg == pytest.approx(5000.0 * ef_g)
    assert c.total_kg == c.electricity_kg + c.gas_kg
    assert str(efs["electricity"].year) in c.ef_source and efs["gas"].source in c.ef_source


def test_sign_follows_saving():
    c = compute_carbon(saving(-3000.0, 12000.0))  # heat pump: electricity rises, gas falls
    assert c.electricity_kg < 0 < c.gas_kg
    assert c.total_kg == c.electricity_kg + c.gas_kg


def test_zero_saving_is_zero_carbon():
    c = compute_carbon(saving(0.0, 0.0))
    assert (c.electricity_kg, c.gas_kg, c.total_kg) == (0.0, 0.0, 0.0)
