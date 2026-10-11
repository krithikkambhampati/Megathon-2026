"""Engine, LLM client and cache wiring (roadmap §5.4). Built ONCE in the FastAPI lifespan.

GREENHOME_ENGINE_MODE:
  engine  (default) → P2's Engine.from_config(); stub vs real models is P2's `config/global.yaml: models`.
  fixture           → FixtureEngine: serves P2's committed tests/fixtures/analysis_result_*.json. For UI work
                      and a demo with no data and no models.
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import Request

from api.cache import ResultCache
from api.errors import APIError
from greenhome.contracts import AnalysisResult, CustomerContext, HomeInput, Scenario

log = logging.getLogger("greenhome.api")

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
DEFAULT_FIXTURE = "P10001"

ModelsMode = Literal["stub", "real", "fixture", "none"]


class FixtureEngine:
    """Same public methods as greenhome.core.orchestrator.Engine, backed by P2's fixture results.

    Picks the fixture matching `home.property_id`, else P10001. A non-default scenario returns the same
    numbers under a new analysis_id (so explain/diff/cache behave as with the real engine).
    """

    def __init__(self, fixtures_dir: Path = FIXTURES_DIR) -> None:
        self.results = {
            p.stem.removeprefix("analysis_result_"): AnalysisResult.model_validate_json(p.read_text("utf-8"))
            for p in sorted(fixtures_dir.glob("analysis_result_*.json"))
        }
        if DEFAULT_FIXTURE not in self.results:
            raise FileNotFoundError(f"{fixtures_dir}/analysis_result_{DEFAULT_FIXTURE}.json is missing")

    @property
    def model_versions(self) -> dict[str, str]:
        return dict(self.results[DEFAULT_FIXTURE].model_versions)

    def _pick(self, home: HomeInput) -> AnalysisResult:
        result = self.results.get(home.property_id or "", self.results[DEFAULT_FIXTURE])
        return result.model_copy(deep=True)

    def analyse(self, home: HomeInput, ctx: CustomerContext | None = None) -> AnalysisResult:
        return self._pick(home)

    def run_scenario(
        self, home: HomeInput, scenario: Scenario, ctx: CustomerContext | None = None
    ) -> AnalysisResult:
        result = self._pick(home)
        if scenario.model_dump() != Scenario().model_dump():
            result.scenario = scenario
            result.analysis_id = hashlib.sha256(
                (result.analysis_id + scenario.model_dump_json()).encode("utf-8")
            ).hexdigest()
        return result


def build_engine() -> Any | None:
    """Returns the engine, or None if it failed to load (routes then answer 503 engine_not_ready)."""
    mode = os.environ.get("GREENHOME_ENGINE_MODE", "engine").strip().lower()
    try:
        if mode == "fixture":
            return FixtureEngine()
        if mode != "engine":
            raise ValueError(f"GREENHOME_ENGINE_MODE must be 'engine' or 'fixture', got {mode!r}")
        from greenhome.core.orchestrator import Engine

        return Engine.from_config()
    except Exception:
        log.exception("engine failed to load (GREENHOME_ENGINE_MODE=%s)", mode)
        return None


def build_llm() -> Any | None:
    """P4's client, or None (templates only). The app must work with the LLM down (BUILD_GUIDE P4.1)."""
    try:
        from greenhome.llm.client import make_client
    except ImportError:
        log.info("greenhome.llm.client not available yet (P4); running without an LLM")
        return None
    try:
        return make_client()
    except Exception:
        log.exception("LLM client failed to start; running without an LLM")
        return None


def engine_info(engine: Any | None) -> tuple[ModelsMode, dict[str, str]]:
    if engine is None:
        return "none", {}
    if isinstance(engine, FixtureEngine):
        return "fixture", engine.model_versions
    return engine.cfg.global_.models, dict(engine.models.versions())


def get_engine(request: Request) -> Any:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise APIError(503, "engine_not_ready", "The analysis engine failed to load. Check the API logs.")
    return engine


def get_cache(request: Request) -> ResultCache:
    return request.app.state.cache


def cached_result(cache: ResultCache, analysis_id: str) -> AnalysisResult:
    result = cache.get(analysis_id)
    if result is None:
        raise APIError(
            404, "analysis_not_found",
            f"No cached analysis {analysis_id!r}. Re-run /v1/analyse or /v1/scenario, then retry.",
        )
    return result
