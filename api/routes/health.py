from typing import Any

from fastapi import APIRouter, Request

from api.deps import engine_info
from api.schemas import HealthResponse
from greenhome.contracts import CONTRACT_VERSION

router = APIRouter()


def _llm_reachable(llm: Any) -> bool:
    """Live check (≤ 2 s) through P4's client; never raises."""
    if llm is None:
        return False
    try:
        return bool(llm.ping(2))
    except Exception:
        return False


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Never fails: reports what is wired up and what isn't."""
    models_mode, model_versions = engine_info(getattr(request.app.state, "engine", None))
    llm_ok = _llm_reachable(getattr(request.app.state, "llm", None))
    return HealthResponse(
        status="ok" if models_mode == "real" and llm_ok else "degraded",
        contract_version=CONTRACT_VERSION,
        model_versions=model_versions,
        models_mode=models_mode,
        llm_ok=llm_ok,
    )
