from __future__ import annotations

from pathlib import Path

import pytest

from greenhome.contracts import ChatRequest, HomeInput, Scenario
from greenhome.core.orchestrator import Engine
from greenhome.llm.chat import SORRY, chat
from greenhome.llm.fake import ScriptedClient
from greenhome.llm.settings import load_llm_settings

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
SETTINGS = load_llm_settings(env={})


@pytest.fixture(scope="module")
def engine() -> Engine:
    return Engine.from_config()


@pytest.fixture(scope="module")
def home() -> HomeInput:
    return HomeInput.model_validate_json((FIXTURES / "home_input_P10001.json").read_text())


@pytest.fixture(scope="module")
def base(engine, home):
    return engine.analyse(home)


def _ask(engine, home, base, message, current=None, llm=None, ctx=None):
    req = ChatRequest(session_id="s1", home=home, message=message, current_scenario=current)
    return chat(req, engine, llm, ctx, base, settings=SETTINGS)


def test_demo_step_6_two_turns(engine, home, base) -> None:
    r1 = _ask(engine, home, base, "What if I only install solar?")
    assert (r1.intent, r1.scenario.mode, r1.scenario.retrofits) == ("whatif", "custom", ["solar_pv"])
    assert r1.result is not None and r1.diff is not None and r1.base_result_id == base.analysis_id
    assert r1.diff.base_analysis_id == base.analysis_id and r1.diff.new_analysis_id == r1.result.analysis_id
    assert r1.memory_proposal is None and r1.check.passed and r1.check.fallback_used
    r2 = _ask(engine, home, base, "and a heat pump but no loft insulation?", current=r1.scenario)
    assert r2.scenario.retrofits == ["solar_pv", "air_source_heat_pump"]
    assert "suitability low" in r2.answer and "Works best after insulating the home first" in r2.answer
    assert "Electricity use goes up while gas use goes down" in r2.answer and r2.check.passed


def test_demo_step_8_memory_is_proposed_not_stored(engine, home, base) -> None:
    r = _ask(engine, home, base, "We installed loft insulation last year and we don't want a heat pump")
    assert r.intent == "memory" and r.result is None and r.diff is None
    assert [e.payload.model_dump() for e in r.memory_proposal] == [
        {"kind": "completed_retrofit", "retrofit": "loft_insulation", "completed_on": None},
        {"kind": "exclude", "retrofit": "air_source_heat_pump"},
    ]
    assert "Nothing is saved until you confirm" in r.answer and r.check.passed


def test_memory_budget_is_shown_back_and_checked(engine, home, base) -> None:
    r = _ask(engine, home, base, "Our budget is £10,000")
    assert r.memory_proposal[0].payload.max_budget_gbp == 10000
    assert "£10,000" in r.answer and r.check.passed


def test_explain_uses_base_or_the_current_scenario(engine, home, base) -> None:
    r = _ask(engine, home, base, "Why is my score only 32?")
    assert r.intent == "explain" and r.result.analysis_id == base.analysis_id and r.diff is None
    current = Scenario(name="only solar_pv", mode="custom", retrofits=["solar_pv", "air_source_heat_pump"])
    r = _ask(engine, home, base, "Why is the heat pump low?", current=current)
    assert r.result.analysis_id != base.analysis_id and r.scenario == current
    assert "Works best after insulating the home first" in r.answer


def test_change_question_during_a_whatif_answers_from_the_diff(engine, home, base) -> None:
    current = Scenario(name="only solar_pv", mode="custom", retrofits=["solar_pv"])
    r = _ask(engine, home, base, "Why did the score change?", current=current)
    assert r.intent == "explain" and r.diff is not None and "Score after the retrofits" in r.answer


@pytest.mark.parametrize(
    "message,intent", [("what is the weather", "out_of_scope"), ("hmm the boiler thing", "unclear")]
)
def test_template_only_intents_keep_the_current_scenario(engine, home, base, message, intent) -> None:
    current = Scenario(name="x", mode="custom", retrofits=["solar_pv"])
    r = _ask(engine, home, base, message, current=current)
    assert r.intent == intent and r.scenario == current and r.result is None
    assert r.check.fallback_used and r.check.attempts == 0 and r.check.passed


def test_unparseable_whatif_asks_a_question(engine, home, base) -> None:
    r = _ask(engine, home, base, "What if my budget was £8,000?")
    assert r.intent == "unclear" and "budget" in r.answer.lower() and r.result is None


def test_infeasible_request_is_rejected_by_the_engine_and_explained(engine, home, base) -> None:
    r = _ask(engine, home, base, "what if I only install solid wall insulation")
    assert [x.retrofit for x in r.result.rejected] == ["solid_wall_insulation"]
    assert "Not possible for your home" in r.answer and "doesn't apply to your type of walls" in r.answer


def test_llm_whatif_answer_is_checked(engine, home, base) -> None:
    bad = "Solar alone saves 99,999 kWh."
    good = "With only solar panels the score after the retrofits would be 43, against 89 with the full plan."
    llm = ScriptedClient([bad, good])
    r = _ask(engine, home, base, "What if I only install solar?", llm=llm)
    assert r.answer == good and r.check.attempts == 2 and not r.check.fallback_used
    assert "Recommended plan" in llm.calls[0].system and "99,999" not in r.answer


def test_engine_errors_never_reach_the_api(home, base) -> None:
    class Broken:
        def run_scenario(self, *a, **k):
            raise RuntimeError("boom")

    r = _ask(Broken(), home, base, "What if I only install solar?")
    assert r.answer == SORRY and r.intent == "unclear" and r.check.fallback_used


def test_bad_override_from_the_engine_becomes_a_question(home, base) -> None:
    class Rejecting:
        def run_scenario(self, *a, **k):
            raise ValueError("duplicate months")

    r = _ask(Rejecting(), home, base, "What if I only install solar?")
    assert r.intent == "unclear" and "couldn't run that scenario" in r.answer


def test_everything_except_the_heat_pump_works_without_the_llm(engine, home, base) -> None:
    r = _ask(engine, home, base, "everything except the heat pump")
    assert r.intent == "whatif" and "air_source_heat_pump" not in r.scenario.retrofits
    assert r.result is not None and r.check.passed and r.check.fallback_used
