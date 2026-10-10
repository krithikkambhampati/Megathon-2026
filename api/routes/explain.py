from fastapi import APIRouter, Depends, Request

from api.cache import ResultCache
from api.deps import cached_result, get_cache
from api.errors import APIError
from api.schemas import ExplainRequest, ExplainResponse

router = APIRouter()


@router.post("/explain", response_model=ExplainResponse)
def explain(
    body: ExplainRequest, request: Request, cache: ResultCache = Depends(get_cache)
) -> ExplainResponse:
    """LLM down → P4 returns template text (still 200). 503 only while P4's explainer isn't installed."""
    try:
        from greenhome.llm.explainer import explain as explain_fn  # P4 (D8), signature per CR-7
    except ImportError:
        raise APIError(503, "explanation_unavailable", "Explanations aren't available yet.") from None
    result = cached_result(cache, body.analysis_id)
    text, check = explain_fn(result, body.section, request.app.state.llm)
    return ExplainResponse(text=text, check=check)
