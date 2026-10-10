"""Error envelope {"error": {"code", "message"}} and handlers (roadmap §5.3)."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.json import NaNSafeJSONResponse

log = logging.getLogger("greenhome.api")


class APIError(Exception):
    """Raise from a route to return a specific status + error code."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(status_code: int, code: str, message: str) -> NaNSafeJSONResponse:
    return NaNSafeJSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


def _first_error(errors: list) -> str:
    if not errors:
        return "invalid request"
    first = errors[0]
    loc = ".".join(str(p) for p in first.get("loc", ()))
    return f"{loc}: {first.get('msg', 'invalid')}" if loc else str(first.get("msg", "invalid"))


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(request: Request, exc: APIError):
        return error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _request_validation_error(request: Request, exc: RequestValidationError):
        return error_response(422, "validation_error", _first_error(exc.errors()))

    @app.exception_handler(ValidationError)
    async def _validation_error(request: Request, exc: ValidationError):
        # e.g. the engine re-validating a scenario override that isn't a valid HomeInput value
        return error_response(422, "validation_error", _first_error(exc.errors()))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        code = "not_found" if exc.status_code == 404 else f"http_{exc.status_code}"
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _internal_error(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "-")
        log.exception("unhandled error request_id=%s", request_id)
        return error_response(500, "internal_error", f"Internal error (request id {request_id})")
