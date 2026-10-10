"""The ONLY number formatter (README §7.1). Engine and models never round; P4 and P5 import these.

Rounding rules: kWh → nearest 10 · kg → nearest 10 · tonnes → 1 dp · £ value → nearest £500 ·
£ cost/bill → nearest £10 · % → 1 dp · score → int · SAP → int. All rounding is half-up.
Every formatter accepts None and returns UNKNOWN (CR-8). Energy and carbon are annual (§7.1).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal

UNKNOWN = "—"
MINUS = "\u2212"  # typographic minus for signed deltas


def round_half_up(x: float, step: float = 1) -> float:
    """Round to the nearest multiple of `step`, halves away from zero (2.5 → 3, -2.5 → -3).

    Uses Decimal on the repr so 29.5 → 30 and 0.15 (1 dp) → 0.2 regardless of binary float error.
    """
    q = Decimal(repr(x)) / Decimal(repr(step))
    return float(q.quantize(Decimal(1), rounding=ROUND_HALF_UP) * Decimal(repr(step)))


def round_score(score_raw: float) -> int:
    """The one place the Green Home Score is rounded."""
    return int(round_half_up(score_raw))


def _num(x: float, step: float, decimals: int = 0) -> str:
    v = round_half_up(x, step)
    if v == 0:
        v = 0.0  # avoid "-0"
    return f"{v:,.{decimals}f}"


def fmt_kwh(x: float | None) -> str:
    return UNKNOWN if x is None else f"{_num(x, 10)} kWh/year"


def fmt_kwh_saving(x: float | None) -> str:
    """Savings are positive = reduction (§7.1). A negative saving reads as an increase, never a saving."""
    if x is None:
        return UNKNOWN
    return f"{fmt_kwh(-x)} increase" if round_half_up(x, 10) < 0 else fmt_kwh(x)


def fmt_kg(x: float | None) -> str:
    return UNKNOWN if x is None else f"{_num(x, 10)} kg CO2e/year"


def fmt_kg_saving(x: float | None) -> str:
    if x is None:
        return UNKNOWN
    return f"{fmt_kg(-x)} increase" if round_half_up(x, 10) < 0 else fmt_kg(x)


def fmt_tonnes(kg: float | None) -> str:
    """Input is kg (engine unit); displayed as tonnes to 1 dp."""
    return UNKNOWN if kg is None else f"{_num(kg / 1000, 0.1, 1)} t CO2e/year"


def _signed_gbp(x: float, step: float) -> str:
    s = _num(abs(x), step)
    return f"{MINUS}£{s}" if round_half_up(x, step) < 0 else f"£{s}"


def fmt_gbp_value(x: float | None) -> str:
    """Property values: nearest £500."""
    return UNKNOWN if x is None else _signed_gbp(x, 500)


def fmt_gbp_cost(x: float | None) -> str:
    """Costs and bills: nearest £10."""
    return UNKNOWN if x is None else _signed_gbp(x, 10)


def fmt_pct(x: float | None) -> str:
    """`*_pct` values (0–100 scale), 1 dp."""
    return UNKNOWN if x is None else f"{_num(x, 0.1, 1)}%"


def fmt_score(x: float | None) -> str:
    return UNKNOWN if x is None else str(round_score(x))


def fmt_sap(x: float | None) -> str:
    return UNKNOWN if x is None else str(int(round_half_up(x)))


def fmt_range(lo: float | None, hi: float | None, fn: Callable[[float | None], str] = fmt_pct) -> str:
    """'a – b' using the given formatter; collapses to one value when both display the same."""
    if lo is None or hi is None:
        return UNKNOWN
    a, b = fn(lo), fn(hi)
    return a if a == b else f"{a} – {b}"


# unit (DiffRow.unit) → (rounding step, decimals, suffix). Percent deltas are percentage points.
_DELTA_UNITS: dict[str, tuple[float, int, str]] = {
    "score": (1, 0, ""),
    "sap": (1, 0, ""),
    "kwh_per_year": (10, 0, " kWh/year"),
    "kg_per_year": (10, 0, " kg CO2e/year"),
    "pct": (0.1, 1, " pp"),
}


def fmt_delta(x: float | None, unit: str) -> str:
    """Always signed: '+16', '−2,950 kWh/year', '+3.5 pp'. Zero after rounding shows as '0'."""
    if x is None:
        return UNKNOWN
    step, decimals, suffix = _DELTA_UNITS[unit]
    v = round_half_up(x, step)
    sign = "+" if v > 0 else MINUS if v < 0 else ""
    return f"{sign}{_num(abs(x), step, decimals)}{suffix}"
