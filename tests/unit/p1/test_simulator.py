"""Behavioural tests for the physics model and retrofit simulator (README P1.9)."""
import numpy as np
import pandas as pd
import pytest

from data_pipeline import physics as ph, simulator as sim
from data_pipeline.kernels_tmp import apply_retrofits, feasible_set

P10001 = dict(property_id="P10001", property_type="semi_detached", age_band="1950_1966", floor_area_m2=85.0,
              bedrooms=3, region="east_midlands", roof_type="pitched_loft", roof_insulation="low",
              wall_type="cavity", wall_insulation="none", glazing="single", gas_connected=True,
              heating_system="gas_boiler_condensing", main_fuel="mains_gas", renewables="none",
              smart_controls="programmer_thermostat")


@pytest.fixture
def home():
    p = pd.DataFrame([P10001] * 200)
    p["property_id"] = [f"P{10001 + i}" for i in range(200)]
    h = ph.draw_hidden(p, np.random.default_rng(0))
    return p, h


def run(p, h, pk):
    return sim.simulate(p, h, 1.0, 1.0, frozenset(pk))


def base(p, h):
    return ph.delivered(p, h, ph.end_uses(p, h))


def test_insulation_only_cuts_gas(home):
    p, h = home
    b, a = base(p, h), run(p, h, {"loft_insulation", "cavity_wall_insulation", "double_glazing"})
    assert (a.gas_kwh < b.gas_kwh).all()
    assert np.allclose(a.electricity_kwh, b.electricity_kwh)


def test_heat_pump_raises_electricity_and_cuts_gas(home):
    p, h = home
    b, a = base(p, h), run(p, h, {"air_source_heat_pump"})
    assert (a.electricity_kwh > b.electricity_kwh).all()
    assert (a.gas_kwh < b.gas_kwh).all()
    assert (a.gas_kwh > 0).all()          # cooking gas remains on the gas meter


def test_solar_only_cuts_grid_import_within_ps_range(home):
    p, h = home
    b, a = base(p, h), run(p, h, {"solar_pv"})
    cut = 1 - a.electricity_kwh / b.electricity_kwh
    assert np.allclose(a.gas_kwh, b.gas_kwh)
    assert (cut > 0).all() and (cut <= 0.35 + 1e-9).all()
    assert np.allclose(a.electricity_demand_kwh, b.electricity_demand_kwh)   # demand unchanged


def test_package_is_not_additive(home):
    p, h = home
    b = base(p, h)
    singles = sum((b.gas_kwh - run(p, h, {r}).gas_kwh) for r in ["loft_insulation", "cavity_wall_insulation"])
    pkg = b.gas_kwh - run(p, h, {"loft_insulation", "cavity_wall_insulation"}).gas_kwh
    assert (pkg < singles).all()          # multiplicative compounding


def test_insulating_first_shrinks_heat_pump_electricity(home):
    p, h = home
    hp = run(p, h, {"air_source_heat_pump"}).electricity_kwh
    hp_ins = run(p, h, {"air_source_heat_pump", "loft_insulation", "cavity_wall_insulation"}).electricity_kwh
    assert (hp_ins < hp).all()


def test_no_negative_energy(home):
    p, h = home
    a = run(p, h, set(ph.RETROFITS))
    assert (a.electricity_kwh >= 0).all() and (a.gas_kwh >= 0).all()


def test_apply_retrofits_idempotent_and_order_free():
    p = pd.DataFrame([P10001])
    once = apply_retrofits(p, frozenset({"loft_insulation", "air_source_heat_pump"}))
    twice = apply_retrofits(once, frozenset({"air_source_heat_pump", "loft_insulation"}))
    pd.testing.assert_frame_equal(once, twice)


def test_flat_with_dwelling_above_has_no_loft_or_solar():
    p = pd.DataFrame([{**P10001, "property_type": "flat", "roof_type": "dwelling_above", "roof_insulation": None}])
    f = feasible_set(p).iloc[0]
    assert not f["loft_insulation"] and not f["solar_pv"]
