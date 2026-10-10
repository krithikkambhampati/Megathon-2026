"""Portfolio: builder (examples source), /v1/portfolio route, and the screen."""

import json
import sys
from pathlib import Path

import pytest
import streamlit as st
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from api import build_portfolio
from api.main import create_app
from greenhome.contracts import PortfolioResponse
from greenhome.core.orchestrator import Engine

ROOT = Path(__file__).resolve().parents[3]
UI = ROOT / "ui"
sys.path.insert(0, str(UI))

import api_client  # noqa: E402


@pytest.fixture
def built(tmp_path, monkeypatch):
    """Build the examples portfolio into a temp folder and point the route at it."""
    monkeypatch.setattr(build_portfolio, "OUT_DIR", tmp_path)
    resp = build_portfolio.build(Engine.from_config(), "test", "examples")
    payload = json.loads(resp.model_dump_json()) | {"source": "examples"}
    (tmp_path / "portfolio_test.json").write_text(json.dumps(payload))
    return resp


def test_builder_ranks_by_improvement_potential(built):
    ips = [r.improvement_potential_pct for r in built.rows]
    known = [x for x in ips if x is not None]
    assert built.total == len(built.rows) > 0
    assert known == sorted(known, reverse=True)
    assert ips[len(known) :] == [None] * (len(ips) - len(known))  # unknown potential ranks last
    assert [r.rank for r in built.rows] == list(range(1, built.total + 1))


@pytest.fixture
def client(built, monkeypatch):
    monkeypatch.setenv("GREENHOME_ENGINE_MODE", "fixture")
    with TestClient(create_app()) as c:
        yield c


def test_route_serves_file_with_limit_and_filter(client, built):
    r = client.get("/v1/portfolio", params={"limit": 2})
    assert r.status_code == 200 and r.headers["x-portfolio-source"] == "examples"
    body = PortfolioResponse.model_validate(r.json())
    assert len(body.rows) == 2 and body.total == built.total
    poor = PortfolioResponse.model_validate(client.get("/v1/portfolio", params={"poor_only": True}).json())
    assert poor.rows and all(x.is_poor for x in poor.rows)
    assert poor.total == sum(1 for x in built.rows if x.is_poor)


def test_route_503_when_not_built(tmp_path, monkeypatch):
    monkeypatch.setattr(build_portfolio, "OUT_DIR", tmp_path)
    monkeypatch.setenv("GREENHOME_ENGINE_MODE", "fixture")
    with TestClient(create_app()) as c:
        r = c.get("/v1/portfolio")
    assert r.status_code == 503 and r.json()["error"]["code"] == "portfolio_not_built"


def test_route_rejects_bad_limit(client):
    assert client.get("/v1/portfolio", params={"limit": 0}).status_code == 422


def test_committed_portfolio_file_is_valid():
    path = ROOT / "outputs" / "portfolio" / "portfolio_test.json"
    if not path.exists():
        pytest.skip("no committed portfolio")
    raw = json.loads(path.read_text())
    assert raw.pop("source") in ("data", "examples")
    PortfolioResponse.model_validate(raw)


def test_screen_renders_table_and_example_label(built, monkeypatch):
    payload = json.loads(built.model_dump_json())
    monkeypatch.setattr(api_client, "portfolio", lambda **kw: payload | {"source": "examples"})
    monkeypatch.setattr(api_client, "BASE_URL", "http://127.0.0.1:9")
    st.cache_data.clear()
    at = AppTest.from_file(str(UI / "pages" / "08_Portfolio.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    assert any("Example portfolio" in i.value for i in at.info)
    assert len(at.dataframe) == 1 and len(at.dataframe[0].value) == built.total
