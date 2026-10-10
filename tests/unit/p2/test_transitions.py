from __future__ import annotations

import itertools

import pytest
from conftest import home_input
from hypothesis import given, settings
from hypothesis import strategies as st

from greenhome.contracts import (
    Glazing,
    HeatingSystem,
    MainFuel,
    Renewables,
    Retrofit,
    RoofInsulation,
    SmartControls,
    WallInsulation,
)
from greenhome.core.transitions import apply_retrofits

RETROFITS = [r.value for r in Retrofit]


def _opt(enum):
    return st.one_of(st.none(), st.sampled_from([e.value for e in enum]))


homes = st.builds(
    lambda **kw: home_input(**kw),
    roof_insulation=_opt(RoofInsulation),
    wall_insulation=_opt(WallInsulation),
    glazing=_opt(Glazing),
    heating_system=_opt(HeatingSystem),
    main_fuel=_opt(MainFuel),
    renewables=_opt(Renewables),
    smart_controls=_opt(SmartControls),
)
packages = st.lists(st.sampled_from(RETROFITS), unique=True)


@pytest.mark.parametrize(
    ("retrofit", "expected"),
    [
        ("loft_insulation", {"roof_insulation": "full"}),
        ("cavity_wall_insulation", {"wall_insulation": "full"}),
        ("solid_wall_insulation", {"wall_insulation": "full"}),
        ("double_glazing", {"glazing": "double"}),
        ("air_source_heat_pump", {"heating_system": "heat_pump", "main_fuel": "electricity"}),
        ("solar_pv", {"renewables": "solar_pv"}),
        ("smart_thermostat", {"smart_controls": "smart_thermostat"}),
    ],
)
def test_each_mapping(retrofit, expected):
    before = home_input()
    after = apply_retrofits(before, [retrofit])
    changed = {k: v for k, v in after.model_dump().items() if before.model_dump()[k] != v}
    assert changed == expected


def test_better_states_are_kept():
    home = home_input(glazing="triple", renewables="solar_pv_battery", smart_controls="smart_zoned")
    after = apply_retrofits(home, ["double_glazing", "solar_pv", "smart_thermostat"])
    assert (after.glazing, after.renewables, after.smart_controls) == (
        "triple", "solar_pv_battery", "smart_zoned",
    )
    unknown_controls = apply_retrofits(home_input(smart_controls=None), ["smart_thermostat"])
    assert unknown_controls.smart_controls == "smart_thermostat"


def test_input_not_mutated_and_energy_unchanged():
    home = home_input()
    snapshot = home.model_dump()
    after = apply_retrofits(home, RETROFITS)
    assert home.model_dump() == snapshot
    assert after.energy == home.energy and after.energy is not home.energy


def test_accepts_enum_members():
    assert apply_retrofits(home_input(), [Retrofit.loft_insulation]).roof_insulation == "full"


def test_unknown_retrofit_raises():
    with pytest.raises(ValueError, match="heat_wand"):
        apply_retrofits(home_input(), ["loft_insulation", "heat_wand"])


@settings(max_examples=150, deadline=None)
@given(home=homes, package=packages)
def test_idempotent(home, package):
    once = apply_retrofits(home, package)
    assert apply_retrofits(once, package) == once


@settings(max_examples=100, deadline=None)
@given(home=homes, package=packages.filter(lambda p: len(p) <= 4))
def test_order_independent(home, package):
    together = apply_retrofits(home, package)
    for perm in itertools.permutations(package):
        assert apply_retrofits(home, perm) == together
        stepwise = home
        for r in perm:
            stepwise = apply_retrofits(stepwise, [r])
        assert stepwise == together
