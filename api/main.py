"""FastAPI app. Run with `make api` (uvicorn api.main:app --port 8000)."""

import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from api.cache import ResultCache
from api.catalogue import Catalogue
from api.deps import build_engine, build_llm, engine_info
from api.errors import register_error_handlers
from api.json import NaNSafeJSONResponse
from api.routes import (
    analyse,
    catalogue,
    chat,
    diff,
    examples,
    explain,
    health,
    labels,
    methodology,
    portfolio,
)

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


class NoCacheStatic(StaticFiles):
    """Static files the browser revalidates, so a demo laptop never shows a stale page after an update."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def _warm_catalogue(app: FastAPI) -> None:
    try:
        app.state.catalogue.cards(app.state.engine)
    except Exception:  # the route will retry and report the error
        log.exception("catalogue warm-up failed")


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("greenhome.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Loaded ONCE here, never per request (README P5 hazard 4).
    app.state.engine = build_engine()  # Engine.from_config() or FixtureEngine (GREENHOME_ENGINE_MODE)
    app.state.llm = build_llm()  # None until P4 ships / if the LLM is down
    app.state.cache = ResultCache(maxsize=512)
    app.state.catalogue = Catalogue()
    if (
        app.state.engine is not None
    ):  # analyse the catalogue homes in the background so the first page is instant
        threading.Thread(target=_warm_catalogue, args=(app,), name="catalogue-warmup", daemon=True).start()
    log.info("engine: %s · llm: %s", engine_info(app.state.engine)[0], "on" if app.state.llm else "off")
    yield


def create_app(web: bool = True) -> FastAPI:
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

    for module in (health, labels, examples, catalogue, analyse, diff, explain, chat, methodology, portfolio):
        app.include_router(module.router, prefix="/v1")
    # The web app (web/): served at "/", after the API so /v1 and /docs keep priority.
    if web and WEB_DIR.exists():
        app.mount("/", NoCacheStatic(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
