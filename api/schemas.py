"""P5-local request/response models (roadmap §5.1).

Models that wrap shared contract types (AnalyseRequest, ExplainResponse, MemoryResponse, ...) are added once
greenhome/contracts.py exists. Until then `_Strict` stands in for contracts.Strict.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(_Strict):
    status: Literal["ok", "degraded"]  # degraded = no engine, stub models or LLM down
    contract_version: str
    model_versions: dict[str, str]
    models_mode: Literal["stub", "real", "fixture", "none"]  # none = engine not wired yet
    llm_ok: bool


class ErrorBody(_Strict):
    code: str
    message: str


class ErrorResponse(_Strict):
    error: ErrorBody
