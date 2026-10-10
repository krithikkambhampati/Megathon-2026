from __future__ import annotations

import pytest

from greenhome.config import RegionCfg, get_config
from greenhome.contracts import EnergyInput
from greenhome.core.annualise import annualise, annualise_fuel

CFG = get_config()
GAS_SHARES = CFG.national.gas_monthly_share
# Dyadic shares (exact in binary floats) so coverage boundaries can be hit exactly: Jan–Apr 1/8, rest 1/16.
EXACT = (0.125,) * 4 + (0.0625,) * 8


def _months(year: int, nums: list[int]) -> list[str]:
    return [f"{year}-{m:02d}" for m in nums]


def _energy(rows: dict[str, dict[str, float | None]], **annual: float) -> EnergyInput:
    return EnergyInput(monthly=[{"month": m, **r} for m, r in rows.items()], **annual)


def _gas_rows(months: list[str], total: float, shares=GAS_SHARES) -> dict[str, dict[str, float | None]]:
    return {m: {"gas_kwh": total * shares[int(m[5:]) - 1]} for m in months}


def _codes(flags, field=None) -> list[str]:
    return [f.code for f in flags if field is None or f.field == field]


@pytest.fixture
def exact_shares(monkeypatch):
    shares = RegionCfg(hdd_factor=1, pv_yield_kwh_per_kwp=1, gas_monthly_share=EXACT,
                       elec_monthly_share=EXACT, pv_monthly_share=EXACT)
    monkeypatch.setattr(CFG, "national", shares)


# ---------- annualise_fuel ----------
def test_fuel_empty_readings():
    assert annualise_fuel({}, GAS_SHARES, 12) == (None, 0.0)


def test_fuel_full_year_recovers_total():
    readings = {m: 12000 * GAS_SHARES[i] for i, m in enumerate(_months(2024, list(range(1, 13))))}
    annual, coverage = annualise_fuel(readings, GAS_SHARES, 12)
    assert coverage == pytest.approx(1.0)
    assert annual == pytest.approx(12000)


def test_fuel_missing_winter_months_scaled_not_zero_filled():
    months = _months(2024, list(range(3, 12)))  # Jan, Feb, Dec missing
    readings = {m: 12000 * GAS_SHARES[int(m[5:]) - 1] for m in months}
    annual, coverage = annualise_fuel(readings, GAS_SHARES, 12)
    naive = sum(readings.values()) / len(readings) * 12
    assert annual == pytest.approx(12000)
    assert annual > naive
    assert annual > sum(readings.values())  # a zero-filled sum would equal this


def test_fuel_coverage_min_boundary():
    shares = (0.25,) * 4 + (0.0,) * 8
    at_min = annualise_fuel({"2024-01": 100.0, "2024-02": 100.0}, shares, 12)
    assert at_min == (400.0, 0.5)
    below = annualise_fuel({"2024-02": 100.0}, shares, 12)
    assert below == (None, 0.25)


def test_fuel_window_ends_at_latest_and_drops_older():
    shares = (1 / 12,) * 12
    readings = {"2022-12": 9999.0, **{m: 10.0 for m in _months(2024, list(range(1, 13)))}}
    annual, coverage = annualise_fuel(readings, shares, 12)
    assert coverage == pytest.approx(1.0)
    assert annual == pytest.approx(120.0)


def test_fuel_window_wraps_year():
    shares = tuple(float(i) for i in range(1, 13))  # distinct per month to identify which ones count
    readings = {"2023-11": 1.0, "2023-12": 1.0, "2024-01": 1.0, "2023-10": 1.0}
    _, coverage = annualise_fuel(readings, shares, 3)
    assert coverage == 11 + 12 + 1  # Nov + Dec + Jan; Oct is outside the 3-month window


# ---------- annualise ----------
def test_annual_only():
    energy, flags = annualise(EnergyInput(annual_electricity_kwh=4800, annual_gas_kwh=12000), "london")
    assert (energy.electricity_kwh, energy.gas_kwh, energy.purchased_kwh) == (4800, 12000, 16800)
    assert energy.source == "annual"
    assert energy.electricity_coverage is None and energy.gas_coverage is None
    assert flags == []


def test_nothing_given():
    energy, flags = annualise(EnergyInput(), None)
    assert energy.source == "none"
    assert energy.purchased_kwh is None and energy.electricity_kwh is None
    assert flags == []


def test_full_monthly_both_fuels():
    elec = CFG.national.elec_monthly_share
    rows = {m: {"electricity_kwh": 4800 * elec[i], "gas_kwh": 12000 * GAS_SHARES[i]}
            for i, m in enumerate(_months(2024, list(range(1, 13))))}
    energy, flags = annualise(_energy(rows), "east_midlands")
    assert energy.electricity_kwh == pytest.approx(4800)
    assert energy.gas_kwh == pytest.approx(12000)
    assert energy.purchased_kwh == pytest.approx(16800)
    assert energy.gas_coverage == pytest.approx(1.0)
    assert energy.source == "monthly"
    assert flags == []


def test_coverage_ok_boundary_has_no_flag(exact_shares):
    rows = _gas_rows(_months(2024, list(range(1, 9))), 1600, EXACT)  # 4/8 + 4/16 = 0.75
    energy, flags = annualise(_energy(rows), None)
    assert energy.gas_coverage == 0.75
    assert energy.gas_kwh == pytest.approx(1600)
    assert flags == []


def test_low_coverage_warns(exact_shares):
    rows = _gas_rows(_months(2024, list(range(1, 8))), 1600, EXACT)  # 0.6875
    energy, flags = annualise(_energy(rows), None)
    assert energy.gas_kwh == pytest.approx(1600)
    assert _codes(flags) == ["LOW_COVERAGE_ANNUALISATION"]
    assert flags[0].severity == "warning" and flags[0].field == "gas_kwh"
    assert flags[0].evidence["coverage"] == 0.6875


def test_coverage_min_boundary_is_low_not_insufficient(exact_shares):
    rows = _gas_rows(_months(2024, [1, 2, 3, 4]), 1600, EXACT)  # exactly 0.5
    energy, flags = annualise(_energy(rows), None)
    assert energy.gas_kwh == pytest.approx(1600)
    assert _codes(flags) == ["LOW_COVERAGE_ANNUALISATION"]


def test_insufficient_monthly_data(exact_shares):
    rows = _gas_rows(_months(2024, [1, 2, 3, 5]), 1600, EXACT)  # 0.4375
    energy, flags = annualise(_energy(rows), None)
    assert energy.gas_kwh is None
    assert energy.gas_coverage == 0.4375
    assert energy.source == "none"
    assert _codes(flags) == ["INSUFFICIENT_MONTHLY_DATA"]


def test_insufficient_monthly_falls_back_to_annual(exact_shares):
    rows = _gas_rows(_months(2024, [1]), 1600, EXACT)
    energy, flags = annualise(_energy(rows, annual_gas_kwh=1500), None)
    assert energy.gas_kwh == 1500
    assert energy.source == "annual"
    assert _codes(flags) == ["INSUFFICIENT_MONTHLY_DATA"]


def test_conflict_prefers_monthly_when_coverage_ok():
    rows = _gas_rows(_months(2024, list(range(1, 13))), 15000)
    energy, flags = annualise(_energy(rows, annual_gas_kwh=12000), None)
    assert energy.gas_kwh == pytest.approx(15000)
    assert _codes(flags) == ["CONFLICT_ANNUAL_VS_MONTHLY"]
    assert flags[0].evidence["annual_given_kwh"] == 12000


def test_conflict_prefers_annual_when_coverage_low(exact_shares):
    rows = _gas_rows(_months(2024, list(range(1, 8))), 2000, EXACT)
    energy, flags = annualise(_energy(rows, annual_gas_kwh=1600), None)
    assert energy.gas_kwh == 1600
    assert energy.source == "annual"
    assert _codes(flags) == ["LOW_COVERAGE_ANNUALISATION", "CONFLICT_ANNUAL_VS_MONTHLY"]


def test_small_difference_no_conflict_uses_monthly():
    rows = _gas_rows(_months(2024, list(range(1, 13))), 13000)  # +8.3%
    energy, flags = annualise(_energy(rows, annual_gas_kwh=12000), None)
    assert energy.gas_kwh == pytest.approx(13000)
    assert flags == []


def test_null_month_is_not_zero():
    rows = _gas_rows(_months(2024, list(range(1, 13))), 12000)
    rows["2024-01"] = {"gas_kwh": None}
    energy, flags = annualise(_energy(rows), None)
    assert energy.gas_coverage == pytest.approx(1 - GAS_SHARES[0])
    assert energy.gas_kwh == pytest.approx(12000)


def test_fuel_without_monthly_values_uses_annual_without_flag():
    rows = {m: {"electricity_kwh": 400.0} for m in _months(2024, list(range(1, 13)))}
    energy, flags = annualise(_energy(rows, annual_gas_kwh=12000), None)
    assert energy.gas_kwh == 12000 and energy.gas_coverage is None
    assert energy.electricity_coverage == pytest.approx(1.0)
    assert energy.source == "monthly"
    assert flags == []


def test_window_is_shared_across_fuels():
    rows = {m: {"gas_kwh": 1000.0} for m in _months(2023, list(range(1, 13)))}
    rows |= {m: {"electricity_kwh": 400.0} for m in _months(2024, list(range(1, 13)))}
    energy, flags = annualise(_energy(rows), None)
    assert energy.gas_kwh is None and energy.gas_coverage == 0.0
    assert _codes(flags, "gas_kwh") == ["INSUFFICIENT_MONTHLY_DATA"]


def test_duplicate_month_raises():
    rows = [{"month": "2024-01", "gas_kwh": 1.0}, {"month": "2024-01", "gas_kwh": 2.0}]
    with pytest.raises(ValueError, match="duplicate"):
        annualise(EnergyInput(monthly=rows), None)
