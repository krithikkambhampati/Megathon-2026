"""P5-local request/response models (roadmap §5.1). Shared types come from greenhome.contracts (P2)."""

from typing import Any, Literal

from greenhome.contracts import CheckReport, CustomerContext, HomeInput, MemoryEvent, Scenario, Strict

Section = Literal["score", "recommendations", "savings", "value"]


class AnalyseRequest(Strict):
    home: HomeInput
    customer_id: str | None = None


class ScenarioRequest(Strict):
    home: HomeInput
    scenario: Scenario
    customer_id: str | None = None


class ExplainRequest(Strict):
    analysis_id: str
    section: Section


class ExplainResponse(Strict):
    text: str
    check: CheckReport


class DiffRequest(Strict):
    base_analysis_id: str
    new_analysis_id: str


class CatalogueItem(Strict):
    id: str
    name: str
    summary: str
    reference: bool  # the challenge brief's reference home
    location: str | None
    property_type: str | None
    era: str | None
    bedrooms: int | None
    floor_area_m2: float | None
    epc_rating: str | None
    heating: str | None
    highlights: list[str]
    score: int | None
    score_class: str | None
    score_after: int | None
    improvement_potential_pct: float | None


class ExampleIndexItem(Strict):
    property_id: str
    title: str
    why_interesting: str
    synthetic: bool = False  # P1 marks made-up homes (e.g. the brief's P10001) so the UI can say so


class HealthResponse(Strict):
    status: Literal["ok", "degraded"]  # degraded = no engine, stub/fixture models or LLM down
    contract_version: str
    model_versions: dict[str, str]
    models_mode: Literal["stub", "real", "fixture", "none"]  # none = engine failed to load
    llm_ok: bool


class MethodologyResponse(Strict):
    contract_version: str
    score_method_version: str
    weights: dict[str, float]
    classes: list[dict[str, Any]]
    sub_score_tables: dict[str, Any]
    intensity_bounds: dict[str, float]
    retrofit_catalogue: list[dict[str, Any]]
    emission_factors: list[dict[str, Any]]
    model_versions: dict[str, str]
    results: dict[str, Any] | None = None  # reports/results_summary.json (headline evaluation results)


class MemoryResponse(Strict):
    customer_id: str
    events: list[MemoryEvent]
    context: CustomerContext


class ErrorBody(Strict):
    code: str
    message: str


class ErrorResponse(Strict):
    error: ErrorBody
