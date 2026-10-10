from __future__ import annotations

from pathlib import Path

import pytest

from greenhome.contracts import AnalysisResult
from greenhome.llm.checker import check, extract_numbers, feedback
from greenhome.llm.facts import build_fact_sheet

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
IDS = ["P10001", "P90002", "P90003", "P90004", "P90005"]


def _result(fx: str) -> AnalysisResult:
    return AnalysisResult.model_validate_json((FIXTURES / f"analysis_result_{fx}.json").read_text())


@pytest.fixture(scope="module")
def p10001() -> AnalysisResult:
    return _result("P10001")


# ---------- extraction ----------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("£350,000", [(350000, "gbp")]),
        ("£350k", [(350000, "gbp")]),
        ("£1.2m", [(1200000, "gbp")]),
        ("2–5%", [(2, "pct"), (5, "pct")]),
        ("2 to 5 %", [(2, "pct"), (5, "pct")]),
        ("2.5% – 3.5%", [(2.5, "pct"), (3.5, "pct")]),
        ("£358,909 to 362,409", [(358909, "gbp"), (362409, "gbp")]),
        ("£400–£1,000", [(400, "gbp"), (1000, "gbp")]),
        ("5,500 kWh", [(5500, "kwh")]),
        ("2 MWh", [(2000, "kwh")]),
        ("1.2 t", [(1200, "co2")]),
        ("1,200 kg", [(1200, "co2")]),
        ("36/100", [(36, "score")]),
        ("+16", [(16, "plain")]),
        ("−2,950 kWh/year", [(2950, "kwh")]),
        ("-3", [(3, "plain")]),
        ("by 2030", [(2030, "year")]),
        ("the 2nd step", [(2, "plain")]),
        ("two thousand kWh", [(2000, "kwh")]),
        ("halves your gas use", [(50, "pct")]),
        ("F7 and CO2e and P10001 and 85 m²", [(85, "plain")]),
        ("double glazing, one of the measures, single glazing", []),
    ],
)
def test_extract_numbers(text, expected) -> None:
    assert [(m.value, m.unit) for m in extract_numbers(text)] == [(float(v), u) for v, u in expected]


def test_negative_sign_is_kept_but_range_dash_is_not() -> None:
    a, b = extract_numbers("−2,950 and 2-5")[0], extract_numbers("2-5")[1]
    assert a.negative and not b.negative


# ---------- matching ----------
SAVINGS_CASES = [
    ("Your home would save 11,130 kWh/year of gas, but electricity use goes up by 1,240 kWh/year.", True),
    ("Electricity rises by 1,240 kWh/year while gas falls by 11,130 kWh/year.", True),
    ("Electricity: 1,240 kWh/year increase.", True),
    ("You would save 1,240 kWh/year of electricity.", False),  # direction
    ("Electricity use falls by 1,240 kWh.", False),  # direction
    ("You'd save around 12,500 kWh of gas.", False),  # invented
    ("Gas use drops from 12,000 kWh/year to 870 kWh/year.", True),
    ("That is roughly 11,100 kWh of gas.", True),  # within 0.5 %
    ("Improvement potential is 58.8%.", True),
    ("Improvement potential is about 59%.", True),
    ("It saves 5% on bills.", False),  # weight-like number, no fact
    ("That would save £400 a year on bills.", False),  # no £ bill figure exists
    ("Carbon falls by 1.9 t CO2e/year.", True),
    ("Carbon falls by 1,870 kg.", True),
    ("Carbon falls by 2.5 t CO2e/year.", False),
    ("Payback in 7 years.", False),  # small int + time unit
    ("There are 3 steps.", True),  # small count
    ("Based on 12 months of readings.", True),
    ("By 2030 you could save more.", False),  # year not in facts
    ("Saving 0 kWh of electricity.", True),
]


@pytest.mark.parametrize("text,ok", SAVINGS_CASES)
def test_savings_sheet_cases(p10001, text, ok) -> None:
    report = check(text, build_fact_sheet(p10001, "savings"))
    assert report.passed is ok, (report.unsupported, report.banned_phrases)


VALUE_CASES = [
    ("Your home is worth £350,000; the indicative change is 2.5% – 3.5%.", True),
    ("The value could be £359,000 – £362,500, but this is indicative and not guaranteed.", True),
    ("The rating could rise from E to C.", True),
    ("This could add £10,000 to your home's value.", False),
    ("We guarantee your value goes up.", False),
    ("Retrofits will increase your property value.", False),
    ("This is not financial advice.", True),
    ("Estimates, not guarantees.", True),
    ("There's no guarantee of a sale price.", True),
    ("You should remortgage.", False),
    ("It is worth exactly 3% more.", False),
]


@pytest.mark.parametrize("text,ok", VALUE_CASES)
def test_value_sheet_cases(p10001, text, ok) -> None:
    report = check(text, build_fact_sheet(p10001, "value"))
    assert report.passed is ok, (report.unsupported, report.banned_phrases)


SCORE_CASES = [
    ("Your Green Home Score is 32 out of 100, which is Poor.", True),
    ("Your score is 32/100.", True),
    ("Energy efficiency carries 25% of the weight; glazing scores 0.", True),
    ("Poor covers scores from 30.", True),
    ("Your score is 38.", False),
    ("After all recommended retrofits it could reach 89.", True),
]


@pytest.mark.parametrize("text,ok", SCORE_CASES)
def test_score_sheet_cases(p10001, text, ok) -> None:
    report = check(text, build_fact_sheet(p10001, "score"))
    assert report.passed is ok, (report.unsupported, report.banned_phrases)


@pytest.mark.parametrize("fx", IDS)
@pytest.mark.parametrize("section", ["score", "recommendations", "savings", "value"])
def test_echoing_every_fact_and_note_passes(fx, section) -> None:
    sheet = build_fact_sheet(_result(fx), section)
    text = ". ".join(f"{f.label} is {f.display}" for f in sheet.facts) + ". " + " ".join(sheet.notes)
    text += " " + " ".join(sheet.reasons.values())
    report = check(text, sheet)
    assert report.passed, report.unsupported


def test_report_fields_and_feedback(p10001) -> None:
    sheet = build_fact_sheet(p10001, "savings")
    r = check("You'd save 1,240 kWh/year of electricity and 99,999 kWh of gas. We guarantee it.", sheet)
    assert not r.passed and r.attempts == 0 and not r.fallback_used
    assert r.numbers_found == ["1,240 kWh", "99,999 kWh"]
    assert "99,999 kWh" in r.unsupported and "1,240 kWh (direction)" in r.unsupported
    fb = feedback(r)
    assert "not in FACTS: 99,999 kWh" in fb and "increases, not savings" in fb and "guarantee" in fb
