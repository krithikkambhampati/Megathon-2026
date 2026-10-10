import math

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from api.errors import APIError
from api.main import create_app


class _Num(BaseModel):
    x: float
    y: float


@pytest.fixture
def client():
    app = create_app()

    @app.get("/_test/nan-dict")
    def nan_dict():
        return {"a": float("nan"), "b": [1.0, float("inf")], "c": {"d": -math.inf}}

    @app.get("/_test/nan-model", response_model=_Num)
    def nan_model():
        return _Num(x=float("nan"), y=2.5)

    @app.post("/_test/echo", response_model=_Num)
    def echo(body: _Num):
        return body

    @app.get("/_test/api-error")
    def api_error():
        raise APIError(404, "analysis_not_found", "no such analysis")

    @app.get("/_test/boom")
    def boom():
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_health_shape(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"status", "contract_version", "model_versions", "models_mode", "llm_ok"}
    assert body["status"] == "degraded"
    assert body["models_mode"] in ("stub", "fixture")
    assert body["llm_ok"] is False


def test_timing_and_request_id_headers(client):
    r = client.get("/v1/health")
    assert "x-response-time-ms" in r.headers
    assert len(r.headers["x-request-id"]) == 8


def test_nan_becomes_null_in_dict(client):
    r = client.get("/_test/nan-dict")
    assert "NaN" not in r.text and "Infinity" not in r.text
    assert r.json() == {"a": None, "b": [1.0, None], "c": {"d": None}}


def test_nan_becomes_null_in_model(client):
    r = client.get("/_test/nan-model")
    assert "NaN" not in r.text
    assert r.json() == {"x": None, "y": 2.5}


def test_validation_error_envelope(client):
    r = client.post("/_test/echo", json={"x": "not a number", "y": 1})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert "x" in err["message"]


def test_api_error_envelope(client):
    r = client.get("/_test/api-error")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "analysis_not_found", "message": "no such analysis"}}


def test_unknown_route_envelope(client):
    r = client.get("/v1/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_internal_error_envelope(client):
    r = client.get("/_test/boom")
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["code"] == "internal_error"
    assert "request id" in err["message"]
