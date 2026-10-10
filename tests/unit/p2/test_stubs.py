from __future__ import annotations

from itertools import combinations

import numpy as np
import pytest
from conftest import home_input, make_clean

from greenhome.contracts import Retrofit
from greenhome.ml.protocols import EnergyModel, RatingModel, RecommenderModel, ValueModel
from greenhome.ml.stubs import (
    StubEnergy,
    StubRating,
    StubRecommender,
    StubValue,
    load_stub_models,
)

ALL = [r.value for r in Retrofit]
HP, LOFT, SOLAR = "air_source_heat_pump", "loft_insulation", "solar_pv"


def _after(clean, *pkgs):
    return StubEnergy().predict_after([clean] * len(pkgs), [frozenset(p) for p in pkgs])


def test_stubs_satisfy_protocols():
    m = load_stub_models()
    assert isinstance(m.energy, EnergyModel)
    assert isinstance(m.rating, RatingModel)
    assert isinstance(m.recommender, RecommenderModel)
    assert isinstance(m.value, ValueModel)
    assert set(m.versions().values()) == {"stub-0"}


def test_empty_package_returns_baseline_exactly():
    (out,) = _after(make_clean(electricity_kwh=4800.123, gas_kwh=12000.456), ())
    assert (out.electricity_kwh, out.gas_kwh) == (4800.123, 12000.456)
    assert out.purchased_kwh == 4800.123 + 12000.456


def test_heat_pump_on_gas_home_gas_falls_electricity_rises():
    (out,) = _after(make_clean(), {HP})
    assert out.gas_kwh == pytest.approx(0.1 * 12000)
    assert out.electricity_kwh == pytest.approx(4800 + 0.9 * 12000 / 3.0)


def test_heat_pump_on_electric_storage_home_divides_heat_by_scop():
    home = home_input(heating_system="electric_storage", main_fuel="electricity")
    (out,) = _after(make_clean(home, gas_kwh=0.0), {HP})
    assert out.electricity_kwh == pytest.approx(0.6 * 4800 / 3.0 + 0.4 * 4800)
    assert out.gas_kwh == 0.0


def test_heat_pump_no_effect_when_already_installed():
    (out,) = _after(make_clean(home_input(heating_system="heat_pump")), {HP})
    assert (out.electricity_kwh, out.gas_kwh) == (4800.0, 12000.0)


def test_solar_changes_only_electricity():
    base, out = _after(make_clean(), (), {SOLAR})
    assert out.gas_kwh == base.gas_kwh
    assert out.electricity_kwh == pytest.approx(4800 * (1 - 0.275))


def test_loft_effect_on_gas_heating():
    (out,) = _after(make_clean(), {LOFT})  # P10001 roof_insulation low → 10–15%
    assert out.gas_kwh == pytest.approx(12000 - 0.7 * 12000 * 0.125)
    assert out.electricity_kwh == 4800.0


def test_interactions_loft_worth_less_after_heat_pump_and_package_not_sum_of_singles():
    base, loft, hp, both = _after(make_clean(), (), {LOFT}, {HP}, {HP, LOFT})
    loft_alone = base.purchased_kwh - loft.purchased_kwh
    loft_after_hp = hp.purchased_kwh - both.purchased_kwh
    assert 0 < loft_after_hp < loft_alone
    singles = (base.purchased_kwh - loft.purchased_kwh) + (base.purchased_kwh - hp.purchased_kwh)
    assert base.purchased_kwh - both.purchased_kwh != pytest.approx(singles)


@pytest.mark.parametrize(
    "overrides,gas",
    [({}, 12000.0), ({"heating_system": "electric_direct", "main_fuel": "electricity"}, 0.0)],
)
def test_outputs_non_negative_for_every_package(overrides, gas):
    clean = make_clean(home_input(**overrides), gas_kwh=gas)
    pkgs = [set(c) for k in range(len(ALL) + 1) for c in combinations(ALL, k)]
    for out in _after(clean, *pkgs):
        assert out.electricity_kwh >= 0 and out.gas_kwh >= 0
        assert out.purchased_kwh == pytest.approx(out.electricity_kwh + out.gas_kwh)


def test_energy_needs_known_baseline():
    with pytest.raises(ValueError):
        _after(make_clean(gas_kwh=None), {LOFT})


def test_batched_length_mismatch_raises():
    with pytest.raises(ValueError):
        StubEnergy().predict_after([make_clean()], [])
    with pytest.raises(ValueError):
        StubValue().predict_log_price([make_clean()], ["E", "D"], "2025-06")


def test_rating_band_midpoint_and_gains():
    homes = [
        make_clean(),  # E, no gain features
        make_clean(home_input(energy_rating=None)),  # unknown → D
        make_clean(home_input(roof_insulation="full", wall_insulation="full", glazing="double")),
        make_clean(home_input(wall_type="solid", wall_insulation="full", heating_system="heat_pump")),
        make_clean(home_input(renewables="solar_pv_battery", smart_controls="smart_zoned")),
    ]
    assert StubRating().predict_sap(homes) == pytest.approx(
        [46.5, 61.5, 46.5 + 4 + 6 + 3, 46.5 + 8 + 10, 46.5 + 6 + 2]
    )


def test_rating_clipped_to_1_100():
    best = home_input(
        energy_rating="A", roof_insulation="full", wall_insulation="full", glazing="triple",
        heating_system="heat_pump", renewables="solar_pv", smart_controls="smart_thermostat",
    )
    assert StubRating().predict_sap([make_clean(best)]) == [100.0]


def test_recommender_half_for_every_retrofit():
    (p,) = StubRecommender().predict_proba([make_clean()])
    assert p == {r: 0.5 for r in ALL}


def test_value_shape_band_step_and_determinism():
    homes = [make_clean()] * 3
    a = StubValue().predict_log_price(homes, ["G", "E", "A"], "2025-06")
    b = StubValue().predict_log_price(homes, ["G", "E", "A"], "2025-06")
    assert a.shape == (20, 3)
    np.testing.assert_array_equal(a, b)
    np.testing.assert_allclose(a[:, 2] - a[:, 0], 6 * 0.015)
    np.testing.assert_allclose(a[:, 1] - a[:, 0], 2 * 0.015)
    assert np.abs(a[:, 0] - np.log(250_000)).max() < 0.05
    assert a[:, 0].std() > 0  # members differ
