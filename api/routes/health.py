from fastapi import APIRouter, Request

from api.schemas import HealthResponse

router = APIRouter()


def _contract_version() -> str:
    try:
        from greenhome.contracts import CONTRACT_VERSION
    except ImportError:
        return "unavailable"
    return CONTRACT_VERSION


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Never fails: reports what is wired up and what isn't."""
    engine = getattr(request.app.state, "engine", None)
    llm = getattr(request.app.state, "llm", None)
    models_mode = getattr(engine, "models_mode", "none") if engine is not None else "none"
    model_versions = dict(getattr(engine, "model_versions", {}) or {}) if engine is not None else {}
    llm_ok = llm is not None  # P5-08: replace with a <= 2 s ping
    status = "ok" if models_mode == "real" and llm_ok else "degraded"
    return HealthResponse(
        status=status,
        contract_version=_contract_version(),
        model_versions=model_versions,
        models_mode=models_mode,
        llm_ok=llm_ok,
    )
