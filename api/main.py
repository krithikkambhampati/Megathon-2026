"""FastAPI app. Run with `make api` (uvicorn api.main:app --port 8000)."""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from api.cache import ResultCache
from api.deps import build_engine, build_llm, engine_info
from api.errors import register_error_handlers
from api.json import NaNSafeJSONResponse
from api.routes import analyse, chat, diff, examples, explain, health, methodology, portfolio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("greenhome.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Loaded ONCE here, never per request (README P5 hazard 4).
    app.state.engine = build_engine()  # Engine.from_config() or FixtureEngine (GREENHOME_ENGINE_MODE)
    app.state.llm = build_llm()  # None until P4 ships / if the LLM is down
    app.state.cache = ResultCache(maxsize=512)
    log.info("engine: %s · llm: %s", engine_info(app.state.engine)[0], "on" if app.state.llm else "off")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Green Home Score API",
        version="0.1.0",
        lifespan=lifespan,
        default_response_class=NaNSafeJSONResponse,
    )
    register_error_handlers(app)

    @app.middleware("http")
    async def timing(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex[:8]
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        log.info("%s %s %s %.1fms", request.method, request.url.path, response.status_code, ms)
        response.headers["X-Response-Time-ms"] = f"{ms:.1f}"
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    for module in (health, examples, analyse, diff, explain, chat, methodology, portfolio):
        app.include_router(module.router, prefix="/v1")
    return app


app = create_app()
