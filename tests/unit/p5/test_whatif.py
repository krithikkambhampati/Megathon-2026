"""What-if screen: scenario toggles, diff table, explanation and chat (AppTest, API faked with the real engine)."""

import json
import sys
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from greenhome.contracts import HomeInput, Scenario
from greenhome.core.diff import diff_results
from greenhome.core.orchestrator import Engine

ROOT = Path(__file__).resolve().parents[3]
UI, FIXTURES = ROOT / "ui", ROOT / "tests" / "fixtures"
PAGE = str(UI / "pages" / "07_What_if.py")
sys.path.insert(0, str(UI))

import api_client  # noqa: E402

ENGINE = Engine.from_config()


def home(pid: str) -> dict:
    return json.loads((FIXTURES / f"home_input_{pid}.json").read_text())


def dump(model) -> dict:
    return json.loads(model.model_dump_json())


@pytest.fixture
def fake_api(monkeypatch):
    """Scenario / diff / explain / chat backed by the real engine, recording what the page sent."""
    calls: dict[str, list] = {"scenario": [], "chat": [], "explain": []}
    cache: dict[str, object] = {}

    def analyse(h, customer_id=None):
        r = ENGINE.analyse(HomeInput.model_validate(h))
        cache[r.analysis_id] = r
        return dump(r)

    def scenario(h, sc, customer_id=None):
        calls["scenario"].append(sc)
        r = ENGINE.run_scenario(HomeInput.model_validate(h), Scenario.model_validate(sc))
        cache[r.analysis_id] = r
        return dump(r)

    def diff(a, b):
        return dump(diff_results(cache[a], cache[b]))

    def explain(analysis_id, section):
        calls["explain"].append((analysis_id, section))
        return {"text": "Solar panels cut your grid electricity.",
                "check": {"passed": True, "numbers_found": ["1"], "unsupported": [], "banned_phrases": [],
                          "attempts": 1, "fallback_used": True}}

    def chat(req):
        calls["chat"].append(req)
        h = HomeInput.model_validate(req["home"])
        base = ENGINE.analyse(h)
        res = ENGINE.run_scenario(h, Scenario(name="custom", mode="custom", retrofits=["solar_pv"]))
        check = {"passed": True, "numbers_found": ["43", "89"], "unsupported": [], "banned_phrases": [],
                 "attempts": 1, "fallback_used": False}
        return {"answer": "With solar panels only, the score after the works is 43.", "intent": "whatif",
                "scenario": dump(res.scenario), "result": dump(res), "base_result_id": base.analysis_id,
                "check": check, "memory_proposal": None, "diff": dump(diff_results(base, res))}

    for name, fn in [("analyse", analyse), ("scenario", scenario), ("diff", diff), ("explain", explain),
                     ("chat", chat)]:
        monkeypatch.setattr(api_client, name, fn)
    monkeypatch.setattr(api_client, "BASE_URL", "http://127.0.0.1:9")
    st.cache_data.clear()
    calls["analyse"] = analyse
    return calls


def open_page(fake_api, pid="P10001") -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=60)
    h = home(pid)
    result = fake_api["analyse"](h)
    at.session_state["home_input"] = h
    at.session_state["analysis"] = result
    at.session_state["base_analysis"] = result
    at.session_state["chat_history"] = []
    return at.run()


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def text(at: AppTest) -> str:
    return "\n".join([m.value for m in at.markdown] + [c.value for c in at.caption] + [w.value for w in at.warning])


def test_toggles_start_at_the_recommended_plan(fake_api):
    at = open_page(fake_api)
    assert not at.exception, at.exception
    plan = at.session_state["base_analysis"]["savings"]["retrofits"]
    assert {c.key.removeprefix("t_") for c in at.checkbox if c.value} == set(plan)


def test_run_solar_only_scenario_shows_diff(fake_api):
    at = open_page(fake_api)
    for c in at.checkbox:
        c.set_value(c.key == "t_solar_pv")
    button(at, "Run this scenario").click().run()
    assert not at.exception, at.exception
    assert fake_api["scenario"][-1] == {"name": "custom", "mode": "custom", "retrofits": ["solar_pv"]}
    t = text(at)
    assert "Score after the works" in t and "Electricity saving" in t
    assert "Left out:" in t  # the other five retrofits
    assert "Estimates, not guarantees." in t


def test_no_retrofits_sends_mode_none(fake_api):
    at = open_page(fake_api)
    for c in at.checkbox:
        c.set_value(False)
    button(at, "Run this scenario").click().run()
    assert fake_api["scenario"][-1]["mode"] == "none"


def test_explain_scenario_shows_badge(fake_api):
    at = open_page(fake_api)
    for c in at.checkbox:
        c.set_value(c.key == "t_solar_pv")
    button(at, "Run this scenario").click().run()
    button(at, "Explain this scenario").click().run()
    assert fake_api["explain"][-1][1] == "savings"
    t = text(at)
    assert "Solar panels cut your grid electricity." in t and "Template answer" in t


def test_reset_restores_plan(fake_api):
    at = open_page(fake_api)
    for c in at.checkbox:
        c.set_value(False)
    button(at, "Reset to the recommended plan").click().run()
    assert all(c.value for c in at.checkbox)
    assert at.session_state["scenario_analysis"] is None


def test_chat_sends_current_scenario_and_syncs_toggles(fake_api):
    at = open_page(fake_api)
    at.chat_input[0].set_value("What if I only install solar panels?").run()
    assert not at.exception, at.exception
    req = fake_api["chat"][-1]
    assert req["message"] == "What if I only install solar panels?" and req["current_scenario"] is None
    assert req["session_id"] and req["home"]["property_id"] == "P10001"
    history = at.session_state["chat_history"]
    assert [h["role"] for h in history] == ["user", "assistant"]
    assert history[1]["badge"] == "✓ all 2 numbers verified"
    assert {c.key for c in at.checkbox if c.value} == {"t_solar_pv"}  # toggles follow the chat scenario
    # a follow-up question carries the scenario on screen
    at.chat_input[0].set_value("and add a smart thermostat").run()
    assert fake_api["chat"][-1]["current_scenario"]["retrofits"] == ["solar_pv"]


def test_insufficient_home_has_no_toggles(fake_api):
    at = open_page(fake_api, "P90003")
    assert not at.exception, at.exception
    assert any("need a savings estimate" in w.value for w in at.warning)
    assert not at.checkbox


def test_without_home_input_points_to_your_home(fake_api):
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["analysis"] = fake_api["analyse"](home("P10001"))
    at.run()
    assert not at.exception
    assert any("Your home" in i.value for i in at.info)
