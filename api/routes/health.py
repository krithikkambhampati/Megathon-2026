from fastapi import APIRouter, Request

from api.deps import engine_info
from api.schemas import HealthResponse
from greenhome.contracts import CONTRACT_VERSION

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Never fails: reports what is wired up and what isn't."""
    models_mode, model_versions = engine_info(getattr(request.app.state, "engine", None))
    llm_ok = getattr(request.app.state, "llm", None) is not None  # TODO(P5): <= 2 s ping once P4 ships
    return HealthResponse(
        status="ok" if models_mode == "real" and llm_ok else "degraded",
        contract_version=CONTRACT_VERSION,
        model_versions=model_versions,
        models_mode=models_mode,
        llm_ok=llm_ok,
    )
