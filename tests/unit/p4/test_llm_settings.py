from __future__ import annotations

from pathlib import Path

import pytest

from greenhome.llm.budget import Deadline
from greenhome.llm.fake import FakeClock
from greenhome.llm.settings import CONFIG_PATH, UNPINNED, load_llm_settings


def test_repo_config_loads_and_is_off_without_env() -> None:
    s = load_llm_settings(env={})
    assert s.provider is None and not s.enabled  # tests and machines without .env run on templates
    assert s.temperature == 0 and s.seed == 42
    assert s.keep_alive == "2h"
    assert (s.answer_budget_s, s.call_timeout_s) == (25, 30)  # P5 sets UI timeouts to 30 s from this


def test_env_overrides_yaml() -> None:
    s = load_llm_settings(
        env={
            "LLM_PROVIDER": "ollama",
            "LLM_MODEL": "m:1",
            "LLM_BASE_URL": "http://x:1",
            "LLM_TIMEOUT_S": "12",
            "LLM_ANSWER_BUDGET_S": "9",
            "LLM_API_KEY": "k",
        }
    )
    assert (s.provider, s.model, s.base_url, s.api_key) == ("ollama", "m:1", "http://x:1", "k")
    assert (s.call_timeout_s, s.answer_budget_s) == (12.0, 9.0)
    assert s.enabled


@pytest.mark.parametrize("value", ["", "none", "off"])
def test_empty_or_none_provider_means_off(value: str) -> None:
    assert load_llm_settings(env={"LLM_PROVIDER": value, "LLM_MODEL": "m:1"}).provider is None


def test_provider_in_yaml_is_ignored(tmp_path: Path) -> None:
    p = tmp_path / "llm.yaml"
    p.write_text(CONFIG_PATH.read_text() + "\nprovider: ollama\n")
    assert load_llm_settings(p, env={}).provider is None


def _unpinned_config(tmp_path: Path) -> Path:
    """config/llm.yaml as it is before `make llm-bench` pins a model (the real file may be pinned)."""
    import re

    p = tmp_path / "llm.yaml"
    p.write_text(re.sub(r"^model: .*$", f"model: {UNPINNED}", CONFIG_PATH.read_text(), count=1, flags=re.M))
    return p


def test_env_example_placeholders_count_as_unset(tmp_path: Path) -> None:
    s = load_llm_settings(
        _unpinned_config(tmp_path), env={"LLM_PROVIDER": "ollama", "LLM_MODEL": "<exact ollama tag>"}
    )
    assert s.model == UNPINNED and not s.enabled


def test_per_prompt_caps_never_exceed_the_call_timeout() -> None:
    s = load_llm_settings(env={"LLM_TIMEOUT_S": "5"})
    assert s.cap("answer") == 5 and s.cap("router") == 4 and s.cap("unknown") == 5
    assert s.min_call_s < s.min_retry_s < s.answer_budget_s


def test_unpinned_model_means_off(tmp_path: Path) -> None:
    s = load_llm_settings(_unpinned_config(tmp_path), env={"LLM_PROVIDER": "ollama"})
    assert s.model == UNPINNED and not s.enabled


def test_pinned_model_with_provider_means_on() -> None:
    s = load_llm_settings(env={"LLM_PROVIDER": "ollama"})
    if s.model != UNPINNED:  # the committed config pins the benchmark winner
        assert s.enabled


def test_bad_provider_rejected() -> None:
    with pytest.raises(ValueError):
        load_llm_settings(env={"LLM_PROVIDER": "claude"})


def test_unknown_yaml_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "llm.yaml"
    p.write_text(CONFIG_PATH.read_text() + "\ntypo_key: 1\n")
    with pytest.raises(ValueError):
        load_llm_settings(p, env={})


def test_deadline_slices_and_expires() -> None:
    clock = FakeClock()
    d = Deadline(25, clock=clock)
    assert d.call_timeout(30) == 25
    clock.advance(20)
    assert d.call_timeout(30) == 5 and d.can_call(3) and not d.can_call(6)
    clock.advance(10)
    assert d.remaining() == 0 and d.expired() and d.call_timeout(30) == 0
