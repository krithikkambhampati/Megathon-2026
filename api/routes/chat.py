from typing import Any

from fastapi import APIRouter, Depends, Request

from api.cache import ResultCache
from api.deps import get_cache, get_engine
from api.errors import APIError
from greenhome.contracts import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    request: Request,
    engine: Any = Depends(get_engine),
    cache: ResultCache = Depends(get_cache),
) -> ChatResponse:
    """P4's chat (CR-7): stateless; the UI keeps the transcript and sends current_scenario for follow-ups.
    LLM down → P4 answers from templates (still 200). 503 only while P4's module isn't installed."""
    try:
        from greenhome.llm.chat import chat as chat_fn
    except ImportError:
        raise APIError(503, "explanation_unavailable", "Chat isn't available yet.") from None
    ctx = None  # TODO(P5-23): CustomerContext from memory when body.customer_id is set
    base = engine.analyse(body.home, ctx)
    cache.put(base)
    resp = chat_fn(body, engine, request.app.state.llm, ctx, base)
    if resp.result is not None:
        cache.put(resp.result)  # so /v1/diff and /v1/explain work on the scenario result
    return resp
