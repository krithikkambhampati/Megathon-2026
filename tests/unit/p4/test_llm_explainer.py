from __future__ import annotations

from pathlib import Path

import pytest

import greenhome.llm.explainer as explainer_mod
from greenhome.contracts import AnalysisResult
from greenhome.llm.budget import Deadline
from greenhome.llm.client import LLMError, LLMTimeout
from greenhome.llm.explainer import UNAVAILABLE, explain, explain_traced, system_prompt
from greenhome.llm.facts import build_fact_sheet
from greenhome.llm.fake import FakeClock, ScriptedClient, Slow
from greenhome.llm.settings import load_llm_settings

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
IDS = ["P10001", "P90002", "P90003", "P90004", "P90005"]
SECTIONS = ["score", "recommendations", "savings", "value"]
GOOD = "Your home would save 11,130 kWh/year of gas, but electricity use goes up by 1,240 kWh/year."
BAD = "You would save 12,500 kWh of gas."
SETTINGS = load_llm_settings(env={})  # repo defaults: budget 25, answer cap 12, min_retry 8


def _result(fx: str) -> AnalysisResult:
    return AnalysisResult.model_validate_json((FIXTURES / f"analysis_result_{fx}.json").read_text())


@pytest.fixture(scope="module")
def p10001() -> AnalysisResult:
    return _result("P10001")


def _trace(result, llm, section="savings", seconds=25.0, clock=None):
    deadline = Deadline(seconds, clock=clock) if clock else Deadline(seconds)
    return explain_traced(result, section, llm, deadline=deadline, settings=SETTINGS)


@pytest.mark.parametrize("fx", IDS)
@pytest.mark.parametrize("section", SECTIONS)
def test_template_answers_pass_the_checker_everywhere(fx, section) -> None:
    text, report = explain(_result(fx), section, None)
    assert text and report.passed and report.fallback_used and report.attempts == 0, report.unsupported


@pytest.mark.parametrize(
    "fx,section,phrase",
    [
        ("P90003", "score", "can't give this home a Green Home Score"),
        ("P90003", "savings", "don't have enough information"),
        ("P90005", "savings", "only modelled for homes heated by mains gas or electricity"),
        ("P90003", "value", "can't estimate a change in property value"),
    ],
)
def test_templates_say_plainly_when_a_section_has_no_numbers(fx, section, phrase) -> None:
    text, report = explain(_result(fx), section, None)
    assert phrase in text and report.numbers_found == []


def test_templates_carry_the_guardrail_wording(p10001) -> None:
    savings, _ = explain(p10001, "savings", None)
    assert "Electricity use goes up while gas use goes down" in savings and "estimates" in savings
    value, _ = explain(p10001, "value", None)
    assert "indicative, not guaranteed or causal" in value and "not financial or mortgage advice" in value


def test_good_llm_answer_is_shown(p10001) -> None:
    llm = ScriptedClient([GOOD])
    t = _trace(p10001, llm)
    assert t.text == GOOD and t.check.passed and t.check.attempts == 1 and not t.check.fallback_used
    assert t.fallback_reason is None and len(llm.calls) == 1
    assert llm.calls[0].timeout_s <= SETTINGS.cap("answer")


def test_failed_check_retries_once_with_feedback(p10001) -> None:
    llm = ScriptedClient([BAD, GOOD])
    t = _trace(p10001, llm)
    assert t.text == GOOD and t.check.attempts == 2 and not t.check.fallback_used
    retry = llm.calls[1].messages
    assert retry[-2] == {"role": "assistant", "content": BAD}
    assert "not in FACTS: 12,500 kWh" in retry[-1]["content"]
    assert [a.report.passed for a in t.attempts] == [False, True]  # raw first attempt kept for the eval


def test_two_failures_fall_back_to_the_template(p10001) -> None:
    t = _trace(p10001, ScriptedClient([BAD, BAD]))
    assert t.check.fallback_used and t.check.attempts == 2 and t.check.passed
    assert t.fallback_reason == "failed_check" and t.text.startswith("If you did all the recommended")


@pytest.mark.parametrize("error", [LLMError("down"), LLMTimeout("slow")])
def test_llm_errors_fall_back_to_the_template(p10001, error) -> None:
    t = _trace(p10001, ScriptedClient([error]))
    assert t.check.fallback_used and t.check.attempts == 0 and t.fallback_reason == "llm_error"


def test_no_retry_without_enough_budget_left(p10001) -> None:
    clock = FakeClock()
    llm = ScriptedClient([Slow(BAD, 10)], clock=clock)
    t = _trace(p10001, llm, seconds=17, clock=clock)  # 17 − 10 = 7 s left < min_retry_s (8): no retry
    assert t.check.fallback_used and t.check.attempts == 1 and len(llm.calls) == 1


def test_spent_budget_skips_the_llm_entirely(p10001) -> None:
    clock = FakeClock()
    deadline = Deadline(25, clock=clock)
    clock.advance(24)
    llm = ScriptedClient([])  # any call would fail the test
    t = explain_traced(p10001, "savings", llm, deadline=deadline, settings=SETTINGS)
    assert t.fallback_reason == "no_time" and t.check.fallback_used


def test_per_call_timeout_never_exceeds_what_is_left(p10001) -> None:
    clock = FakeClock()
    llm = ScriptedClient([Slow(BAD, 5), GOOD], clock=clock)
    _trace(p10001, llm, seconds=14, clock=clock)
    assert llm.calls[0].timeout_s == 12 and llm.calls[1].timeout_s == 9


def test_explain_never_raises(monkeypatch, p10001) -> None:
    def boom(*a, **k):
        raise RuntimeError("bug in facts")

    monkeypatch.setattr(explainer_mod, "build_fact_sheet", boom)
    text, report = explain(p10001, "score", ScriptedClient([]))
    assert text == UNAVAILABLE and report.fallback_used
    text, report = explain(p10001, "everything", None)  # type: ignore[arg-type]
    assert text == UNAVAILABLE


def test_system_prompt_has_the_readme_rules_and_the_facts(p10001) -> None:
    sheet = build_fact_sheet(p10001, "savings")
    prompt = system_prompt(sheet, "Explain.")
    for rule in (
        'Use ONLY numbers that appear in FACTS, copied exactly as their "display" text.',
        "Never calculate, add, subtract, convert, round or estimate a number yourself.",
        "If the user asks for something not in FACTS, say it isn't available from this tool.",
        'Savings are "estimated". Property value changes are "indicative" and not guaranteed or causal.',
        "If DATA_NOTES list missing, assumed or conflicting data, mention the ones that affect your answer.",
        "Never recommend a retrofit marked infeasible. Explain its REASON instead.",
        "If electricity use goes up while gas goes down, say so explicitly.",
        "No financial or mortgage advice. Plain English, at most 170 words, no tables.",
    ):
        assert rule in prompt
    assert "1,240 kWh/year increase" in prompt and "1243.54" not in prompt
