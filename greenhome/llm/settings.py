"""LLM settings (README P4.1, §5.4): `config/llm.yaml` with environment overrides.

P4's own small loader, so P2's `greenhome/config.py` stays untouched. Env always wins over the YAML, and the
provider comes from env only, so tests and machines without a `.env` run on templates. Nothing here loads
`.env`; the process environment carries it (`uv run --env-file .env`).
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "llm.yaml"
UNPINNED = "TODO_PIN_AFTER_BENCH"
_PLACEHOLDER = re.compile(r"^<.*>$")  # e.g. "<exact ollama tag>" copied from .env.example

Provider = Literal["ollama", "openai_compat"]

# env var → (settings field, type). LLM_PROVIDER / LLM_MODEL / LLM_BASE_URL / LLM_API_KEY / LLM_TIMEOUT_S
# are the README §5.4 names; LLM_ANSWER_BUDGET_S is P4's (P5 request: one budget per answer).
_ENV: dict[str, tuple[str, type]] = {
    "LLM_PROVIDER": ("provider", str),
    "LLM_MODEL": ("model", str),
    "LLM_BASE_URL": ("base_url", str),
    "LLM_API_KEY": ("api_key", str),
    "LLM_TIMEOUT_S": ("call_timeout_s", float),
    "LLM_ANSWER_BUDGET_S": ("answer_budget_s", float),
}


class LLMSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Provider | None = None
    model: str = UNPINNED
    base_url: str = "http://localhost:11434"
    api_key: str | None = None
    candidates: list[str] = []
    temperature: float = 0.0
    seed: int = 42
    num_ctx: int = 4096
    keep_alive: str = "2h"
    answer_budget_s: float = 25.0
    call_timeout_s: float = 30.0
    call_cap_s: dict[str, float] = {}
    min_call_s: float = 3.0
    min_retry_s: float = 8.0
    connect_timeout_s: float = 2.0
    warmup_timeout_s: float = 120.0
    max_tokens: dict[str, int] = {}
    cache_max_entries: int = 1024

    @property
    def enabled(self) -> bool:
        """An LLM is configured: provider set and a real model tag pinned."""
        return self.provider is not None and bool(self.model) and self.model != UNPINNED

    def tokens(self, prompt: str, default: int = 300) -> int:
        return self.max_tokens.get(prompt, default)

    def cap(self, prompt: str) -> float:
        """Timeout cap for one call of this prompt kind (never above call_timeout_s)."""
        return min(self.call_cap_s.get(prompt, self.call_timeout_s), self.call_timeout_s)


def load_llm_settings(path: Path = CONFIG_PATH, env: dict[str, str] | None = None) -> LLMSettings:
    """YAML first, then env overrides. Empty env values count as unset."""
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    data = dict(data or {})
    data.pop("provider", None)  # env only
    env = os.environ if env is None else env
    for var, (field, typ) in _ENV.items():
        raw = env.get(var, "").strip()
        if raw and not _PLACEHOLDER.match(raw):
            data[field] = typ(raw)
    if data.get("provider") in ("none", "off"):
        data["provider"] = None
    return LLMSettings.model_validate(data)


@lru_cache(maxsize=1)
def get_llm_settings() -> LLMSettings:
    return load_llm_settings()
