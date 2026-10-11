"""Monthly readings → annual kWh per fuel, weighted by seasonal shares (BUILD_GUIDE P2.2 step 2).

coverage = Σ regional monthly share (regions.yaml) over the window months that have a reading. A missing
month is never treated as 0: the readings are scaled up by 1/coverage instead. Typical-home imputation of
missing energy lives in `validate.py`, not here.

Per-fuel coverage is reported only when that fuel has at least one monthly value; otherwise it is None.
"""

from __future__ import annotations

from collections.abc import Sequence

from greenhome.config import get_config
from greenhome.contracts import AnnualEnergy, DataFlag, EnergyInput

# (AnnualEnergy / MonthlyReading field, RegionCfg share field, EnergyInput annual field)
_FUELS = (
    ("electricity_kwh", "elec_monthly_share", "annual_electricity_kwh"),
    ("gas_kwh", "gas_monthly_share", "annual_gas_kwh"),
)


def _month_index(month: str) -> int:
    """'YYYY-MM' → months since year 0, so windows wrap across years; index % 12 = month - 1."""
    year, mon = month.split("-")
    return int(year) * 12 + int(mon) - 1


def annualise_fuel(
    readings: dict[str, float], shares: Sequence[float], window: int
) -> tuple[float | None, float]:
    """(annual kWh or None, coverage) over the `window` months ending at the latest month in `readings`."""
    if not readings:
        return None, 0.0
    by_index = {_month_index(m): kwh for m, kwh in readings.items()}
    end = max(by_index)
    in_window = {i: kwh for i, kwh in by_index.items() if i > end - window}
    coverage = sum(shares[i % 12] for i in in_window)
    if coverage < get_config().engine.annualise.coverage_min:
        return None, coverage
    return sum(in_window.values()) / coverage, coverage


def annualise(energy: EnergyInput, region: str | None) -> tuple[AnnualEnergy, list[DataFlag]]:
    """Per-fuel monthly-vs-annual choice. Both fuels share one window ending at the latest month supplied.

    Raises ValueError on duplicate months.
    """
    cfg = get_config()
    a = cfg.engine.annualise
    region_cfg = cfg.region(region)
    rows = energy.monthly or []
    months = [r.month for r in rows]
    if len(set(months)) != len(months):
        dupes = sorted({m for m in months if months.count(m) > 1})
        raise ValueError(f"duplicate months in monthly readings: {dupes}")
    end = max(map(_month_index, months), default=0)

    values: dict[str, float | None] = {}
    coverages: dict[str, float | None] = {}
    flags: list[DataFlag] = []
    from_monthly = from_annual = False
    for fuel, share_field, annual_field in _FUELS:
        given = getattr(energy, annual_field)
        label = fuel.removesuffix("_kwh")
        has_monthly = any(getattr(r, fuel) is not None for r in rows)
        readings = {
            r.month: getattr(r, fuel)
            for r in rows
            if getattr(r, fuel) is not None and _month_index(r.month) > end - a.months_window
        }
        estimate, coverage = (
            annualise_fuel(readings, getattr(region_cfg, share_field), a.months_window)
            if has_monthly
            else (None, None)
        )
        evidence = {"coverage": coverage, "monthly_estimate_kwh": estimate, "annual_given_kwh": given}
        if estimate is not None and coverage < a.coverage_ok:
            flags.append(DataFlag(
                code="LOW_COVERAGE_ANNUALISATION", severity="warning", field=fuel, evidence=evidence,
                message=f"Monthly {label} readings cover part of the year; the annual figure is scaled up.",
            ))
        if has_monthly and estimate is None:
            flags.append(DataFlag(
                code="INSUFFICIENT_MONTHLY_DATA", severity="warning", field=fuel, evidence=evidence,
                message=f"Too few monthly {label} readings to estimate a full year.",
            ))
        use_monthly = estimate is not None
        if estimate is not None and given is not None and abs(estimate - given) > a.conflict_rel_diff * given:
            use_monthly = coverage >= a.coverage_ok
            flags.append(DataFlag(
                code="CONFLICT_ANNUAL_VS_MONTHLY", severity="warning", field=fuel, evidence=evidence,
                message=f"Annual and monthly {label} figures disagree; using the "
                f"{'monthly' if use_monthly else 'annual'} figure.",
            ))
        values[fuel] = estimate if use_monthly else given
        coverages[fuel] = coverage
        from_monthly |= use_monthly
        from_annual |= not use_monthly and given is not None

    elec, gas = values["electricity_kwh"], values["gas_kwh"]
    return AnnualEnergy(
        electricity_kwh=elec,
        gas_kwh=gas,
        purchased_kwh=None if elec is None or gas is None else elec + gas,
        electricity_coverage=coverages["electricity_kwh"],
        gas_coverage=coverages["gas_kwh"],
        source="monthly" if from_monthly else "annual" if from_annual else "none",
    ), flags
