"""Stub models (README P2.1): deterministic stand-ins for P3's models, implementing ml/protocols.py (§7.6).

The engine, fixtures and every other part build against these until P3 ships `models/`. The numbers below
are the README P2.1 stub constants, the one allowed set of literals outside config (ROADMAP convention 3).
"""

from __future__ import annotations

import numpy as np

from greenhome.config import get_config
from greenhome.contracts import (
    CleanHome,
    EnergyRating,
    FuelEnergy,
    HeatingSystem,
    MainFuel,
    Retrofit,
)
from greenhome.ml.protocols import Models

VERSION = "stub-0"
GAS_HEAT_SHARE = 0.7  # share of gas used for space heating in a gas-heated home
ELEC_HEAT_SHARE = 0.6  # share of electricity used for space heating in an electrically heated home
HP_GAS_RESIDUAL = 0.1  # gas left after a heat pump (cooking, backup)
HP_GAS_TO_ELEC = 0.9  # share of displaced gas heat the heat pump supplies
STUB_SCOP = 3.0
DEFAULT_BAND = "D"  # rating used when the band is unknown
# (all field conditions that must hold, SAP gain)
SAP_GAINS: tuple[tuple[dict[str, tuple[str, ...]], float], ...] = (
    ({"roof_insulation": ("full",)}, 4.0),
    ({"wall_type": ("cavity",), "wall_insulation": ("full",)}, 6.0),
    ({"wall_type": ("solid",), "wall_insulation": ("full",)}, 8.0),
    ({"glazing": ("double", "triple")}, 3.0),
    ({"heating_system": ("heat_pump",)}, 10.0),
    ({"renewables": ("solar_pv", "solar_pv_battery")}, 6.0),
    ({"smart_controls": ("smart_thermostat", "smart_zoned")}, 2.0),
)
STUB_P_ASSESSOR = 0.5
BASE_PRICE_GBP = 250_000.0
LOG_PRICE_PER_BAND = 0.015
MEMBER_NOISE_SD = 0.005
N_MEMBERS = 20

_ELECTRIC_HEATING = (HeatingSystem.electric_storage, HeatingSystem.electric_direct)


def _check_len(a: list, b: list) -> None:
    if len(a) != len(b):
        raise ValueError(f"batch length mismatch: {len(a)} homes vs {len(b)}")


class StubEnergy:
    version = VERSION

    def predict_after(self, homes: list[CleanHome], packages: list[frozenset[Retrofit]]) -> list[FuelEnergy]:
        _check_len(homes, packages)
        return [self._one(h, p) for h, p in zip(homes, packages, strict=True)]

    @staticmethod
    def _one(clean: CleanHome, package: frozenset[Retrofit]) -> FuelEnergy:
        elec, gas = clean.energy.electricity_kwh, clean.energy.gas_kwh
        if elec is None or gas is None:
            raise ValueError("StubEnergy needs a known electricity and gas baseline")
        names = {str(r) for r in package}
        if names:
            elec, gas = _after(clean, names, elec, gas)
        elec, gas = max(elec, 0.0), max(gas, 0.0)
        return FuelEnergy(electricity_kwh=elec, gas_kwh=gas, purchased_kwh=elec + gas)


def _after(clean: CleanHome, names: set[str], elec: float, gas: float) -> tuple[float, float]:
    home, cat = clean.home, get_config().catalogue
    gas_heated = home.main_fuel == MainFuel.mains_gas
    fuel = gas if gas_heated else elec
    heat = (GAS_HEAT_SHARE if gas_heated else ELEC_HEAT_SHARE) * fuel
    other = fuel - heat
    for r in Retrofit:
        spec = cat[r.value]
        if r.value in names and spec.applies_to_end_use == "space_heating":
            state = getattr(home, spec.state_field) if spec.state_field else None
            heat *= 1 - spec.effect_mid_frac(state)
    heat_pump = (
        Retrofit.air_source_heat_pump.value in names and home.heating_system != HeatingSystem.heat_pump
    )
    if gas_heated:
        gas = heat + other
        if heat_pump:
            elec += HP_GAS_TO_ELEC * gas / STUB_SCOP
            gas *= HP_GAS_RESIDUAL
    else:
        if heat_pump and home.heating_system in _ELECTRIC_HEATING:
            heat /= STUB_SCOP
        elec = heat + other
    if Retrofit.solar_pv.value in names:
        elec *= 1 - cat[Retrofit.solar_pv.value].effect_mid_frac(home.renewables)
    return elec, gas


class StubRating:
    version = VERSION

    def predict_sap(self, homes: list[CleanHome]) -> list[float]:
        bands = get_config().engine.sap_bands
        sap_min = min(lo for lo, _ in bands.values())
        sap_max = max(hi for _, hi in bands.values())
        out = []
        for clean in homes:
            home = clean.home
            lo, hi = bands[home.energy_rating or DEFAULT_BAND]
            sap = (lo + hi) / 2 + sum(
                gain
                for conds, gain in SAP_GAINS
                if all(getattr(home, f) in values for f, values in conds.items())
            )
            out.append(float(min(max(sap, sap_min), sap_max)))
        return out


class StubRecommender:
    version = VERSION

    def predict_proba(self, homes: list[CleanHome]) -> list[dict[Retrofit, float]]:
        return [{r.value: STUB_P_ASSESSOR for r in Retrofit} for _ in homes]


class StubValue:
    version = VERSION

    def __init__(self) -> None:
        rng = np.random.default_rng(get_config().global_.seed)
        self._offsets = rng.normal(0.0, MEMBER_NOISE_SD, N_MEMBERS)

    def predict_log_price(
        self, homes: list[CleanHome], ratings: list[EnergyRating], as_of: str
    ) -> np.ndarray:
        _check_len(homes, ratings)
        worst_first = [e.value for e in reversed(EnergyRating)]  # G=0 … A=6
        idx = np.array([worst_first.index(str(r)) for r in ratings], dtype=float)
        return np.log(BASE_PRICE_GBP) + LOG_PRICE_PER_BAND * idx[None, :] + self._offsets[:, None]


def load_stub_models() -> Models:
    return Models(energy=StubEnergy(), rating=StubRating(), recommender=StubRecommender(), value=StubValue())
