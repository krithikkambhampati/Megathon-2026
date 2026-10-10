"""The ONLY place the UI talks to the API. All numbers come from here (README P5 hazard 1)."""

import os
from typing import Any

import httpx

BASE_URL = os.environ.get("GREENHOME_API_URL", "http://localhost:8000").rstrip("/")
DEFAULT_TIMEOUT_S = 15
CHAT_TIMEOUT_S = 60
HEALTH_TIMEOUT_S = 5


class APIError(Exception):
    """status 0 = API unreachable; otherwise the HTTP status + the API's error code."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code
        self.message = message


def _request(method: str, path: str, *, json: Any = None, params: dict | None = None,
             timeout: float = DEFAULT_TIMEOUT_S) -> Any:
    try:
        r = httpx.request(method, f"{BASE_URL}{path}", json=json, params=params, timeout=timeout)
    except httpx.HTTPError as exc:
        raise APIError(0, "api_unreachable", f"{BASE_URL}: {exc}") from exc
    if r.status_code >= 400:
        try:
            err = r.json()["error"]
            raise APIError(r.status_code, err["code"], err["message"])
        except (ValueError, KeyError, TypeError):
            raise APIError(r.status_code, f"http_{r.status_code}", r.text[:200]) from None
    return r.json()


def health() -> dict:
    return _request("GET", "/v1/health", timeout=HEALTH_TIMEOUT_S)
