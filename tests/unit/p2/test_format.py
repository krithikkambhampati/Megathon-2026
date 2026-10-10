"""format.py: README §7.1 rounding rules and CR-8 display strings."""

from __future__ import annotations

import pytest

from greenhome import format as f


@pytest.mark.parametrize(("x", "expected"), [(29.5, 30), (79.5, 80), (79.49, 79), (36.088, 36), (0.5, 1)])
def test_round_score_half_up(x, expected) -> None:
    assert f.round_score(x) == expected


@pytest.mark.parametrize(("fn", "x", "expected"), [
    (f.fmt_kwh, 12004, "12,000 kWh/year"),
    (f.fmt_kwh, 12005, "12,010 kWh/year"),
    (f.fmt_kwh_saving, 2520, "2,520 kWh/year"),
    (f.fmt_kwh_saving, -2950, "2,950 kWh/year increase"),
    (f.fmt_kg, 1234, "1,230 kg CO2e/year"),
    (f.fmt_kg_saving, -1234, "1,230 kg CO2e/year increase"),
    (f.fmt_tonnes, 1234, "1.2 t CO2e/year"),
    (f.fmt_tonnes, 1250, "1.3 t CO2e/year"),
    (f.fmt_gbp_value, 357249, "£357,000"),
    (f.fmt_gbp_value, 357250, "£357,500"),
    (f.fmt_gbp_cost, 1485, "£1,490"),
    (f.fmt_pct, 3.45, "3.5%"),
    (f.fmt_pct, 0.15, "0.2%"),
    (f.fmt_score, 36.088, "36"),
    (f.fmt_points, 11.75, "11.8"),
    (f.fmt_points, 4.4616, "4.5"),
    (f.fmt_intensity, 197.65, "198 kWh/m²/year"),
    (f.fmt_area, 87.0, "87 m²"),
    (f.fmt_area, 89.5, "90 m²"),
    (f.fmt_area, 1234.4, "1,234 m²"),
    (f.fmt_intensity, 1234.4, "1,234 kWh/m²/year"),
    (f.fmt_sap, 61.5, "62"),
])
def test_formatters(fn, x, expected) -> None:
    assert fn(x) == expected


def test_every_formatter_handles_none() -> None:
    for fn in (f.fmt_kwh, f.fmt_kwh_saving, f.fmt_kg, f.fmt_kg_saving, f.fmt_tonnes, f.fmt_gbp_value,
               f.fmt_gbp_cost, f.fmt_pct, f.fmt_score, f.fmt_sap, f.fmt_points, f.fmt_intensity, f.fmt_area):
        assert fn(None) == f.UNKNOWN == "—"
    assert f.fmt_range(None, 1) == f.fmt_delta(None, "score") == "—"


def test_no_negative_zero() -> None:
    assert f.fmt_kwh(-4) == "0 kWh/year"
    assert f.fmt_kwh_saving(-4) == "0 kWh/year"


def test_range() -> None:
    assert f.fmt_range(357000, 367400, f.fmt_gbp_value) == "£357,000 – £367,500"
    assert f.fmt_range(3.44, 3.45, f.fmt_pct) == "3.4% – 3.5%"
    assert f.fmt_range(3.46, 3.54, f.fmt_pct) == "3.5%"


@pytest.mark.parametrize(("x", "unit", "expected"), [
    (16, "score", "+16"),
    (-2950, "kwh_per_year", "−2,950 kWh/year"),
    (3.45, "pct", "+3.5 pp"),
    (-1234, "kg_per_year", "−1,230 kg CO2e/year"),
    (0.2, "score", "0"),
    (4.6, "sap", "+5"),
])
def test_delta_always_signed(x, unit, expected) -> None:
    assert f.fmt_delta(x, unit) == expected
