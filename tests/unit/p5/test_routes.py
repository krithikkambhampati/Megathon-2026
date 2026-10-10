import json
import sys
import types
from pathlib import Path
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from greenhome.contracts import CONTRACT_VERSION, CheckReport, DiffKey, HomeInput

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
HOME_IDS = sorted(p.stem.removeprefix("home_input_") for p in FIXTURES.glob("home_input_*.json"))


def _home(pid: str) -> dict:
    return json.loads((FIXTURES / f"home_input_{pid}.json").read_text())


def _client(monkeypatch, mode: str) -> TestClient:
    monkeypatch.setenv("GREENHOME_ENGINE_MODE", mode)
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.fixture
def fixture_client(monkeypatch):
    with _client(monkeypatch, "fixture") as c:
        yield c


@pytest.fixture
def engine_client(monkeypatch):
    with _client(monkeypatch, "engine") as c:
        yield c


def _no_nan(text: str) -> None:
    assert "NaN" not in text and "Infinity" not in text


# ---------- health ----------
def test_health_fixture_mode(fixture_client):
    body = fixture_client.get("/v1/health").json()
    assert body["models_mode"] == "fixture"
    assert body["contract_version"] == CONTRACT_VERSION
    assert body["model_versions"]  # taken from the fixture
    assert body["status"] == "degraded"


def test_health_engine_mode(engine_client):
    body = engine_client.get("/v1/health").json()
    assert body["models_mode"] == "stub"
    assert set(body["model_versions"]) == {"energy", "rating", "recommender", "value"}


def test_engine_not_ready(monkeypatch):
    with _client(monkeypatch, "bogus") as c:
        assert c.get("/v1/health").json()["models_mode"] == "none"
        r = c.post("/v1/analyse", json={"home": _home("P10001")})
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "engine_not_ready"


# ---------- examples ----------
def test_examples_list_falls_back_to_fixtures(fixture_client):
    items = fixture_client.get("/v1/examples").json()
    assert [i["property_id"] for i in items] == HOME_IDS
    assert all(i["title"] and i["why_interesting"] for i in items)


@pytest.mark.parametrize("pid", HOME_IDS)
def test_example_is_valid_home_input(fixture_client, pid):
    r = fixture_client.get(f"/v1/examples/{pid}")
    assert r.status_code == 200
    HomeInput.model_validate(r.json())


@pytest.mark.parametrize("bad", ["P99999", "..%2Fpyproject", "x"])
def test_example_not_found(fixture_client, bad):
    r = fixture_client.get(f"/v1/examples/{bad}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] in ("example_not_found", "not_found")


# ---------- analyse / scenario ----------
def test_analyse_fixture_mode_returns_matching_fixture(fixture_client):
    r = fixture_client.post("/v1/analyse", json={"home": _home("P90003")})
    assert r.status_code == 200
    assert r.json()["score"]["status"] == "insufficient"
    _no_nan(r.text)


@pytest.mark.parametrize("pid", HOME_IDS)
def test_analyse_engine_mode(engine_client, pid):
    r = engine_client.post("/v1/analyse", json={"home": _home(pid)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contract_version"] == CONTRACT_VERSION
    assert len(body["recommendations"]) == 7
    _no_nan(r.text)


def test_analyse_validation_error(engine_client):
    home = _home("P10001") | {"glazing": "Double glazed"}
    r = engine_client.post("/v1/analyse", json={"home": home})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error" and "glazing" in err["message"]


def test_scenario_bad_override_is_422(engine_client):
    body = {"home": _home("P10001"), "scenario": {"overrides": {"glazing": "quadruple"}}}
    r = engine_client.post("/v1/scenario", json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_scenario_and_diff_engine_mode(engine_client):
    home = _home("P10001")
    base = engine_client.post("/v1/analyse", json={"home": home}).json()
    scen = engine_client.post(
        "/v1/scenario",
        json={"home": home, "scenario": {"name": "solar only", "mode": "custom", "retrofits": ["solar_pv"]}},
    )
    assert scen.status_code == 200, scen.text
    new = scen.json()
    assert new["analysis_id"] != base["analysis_id"]
    assert new["savings"]["retrofits"] == ["solar_pv"]

    d = engine_client.post(
        "/v1/diff", json={"base_analysis_id": base["analysis_id"], "new_analysis_id": new["analysis_id"]}
    )
    assert d.status_code == 200, d.text
    rows = d.json()["rows"]
    assert [r["key"] for r in rows] == list(get_args(DiffKey))
    after = {r["key"]: r for r in rows}["score_after"]
    assert after["new"] != after["base"]  # solar-only vs the full package: the after-score must differ
    _no_nan(d.text)


def test_scenario_and_diff_fixture_mode(fixture_client):
    home = _home("P10001")
    base = fixture_client.post("/v1/analyse", json={"home": home}).json()
    new = fixture_client.post(
        "/v1/scenario", json={"home": home, "scenario": {"mode": "custom", "retrofits": ["solar_pv"]}}
    ).json()
    assert new["analysis_id"] != base["analysis_id"]
    d = fixture_client.post(
        "/v1/diff", json={"base_analysis_id": base["analysis_id"], "new_analysis_id": new["analysis_id"]}
    )
    assert d.status_code == 200


def test_diff_unknown_id(fixture_client):
    r = fixture_client.post("/v1/diff", json={"base_analysis_id": "nope", "new_analysis_id": "nope2"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "analysis_not_found"


# ---------- explain ----------
def test_explain_unavailable_without_p4_module(fixture_client, monkeypatch):
    # None in sys.modules makes the import raise ImportError, whether or not P4 has shipped the file
    monkeypatch.setitem(sys.modules, "greenhome.llm.explainer", None)
    r = fixture_client.post("/v1/explain", json={"analysis_id": "x", "section": "score"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "explanation_unavailable"


@pytest.fixture
def fake_explainer(monkeypatch):
    """Stand-in for P4's greenhome.llm.explainer with the CR-7 signature."""
    module = types.ModuleType("greenhome.llm.explainer")

    def explain(result, section, llm):
        check = CheckReport(passed=True, numbers_found=[], unsupported=[], banned_phrases=[],
                            attempts=1, fallback_used=llm is None)
        return f"{section} explanation for {result.analysis_id[:8]}", check

    module.explain = explain
    monkeypatch.setitem(sys.modules, "greenhome.llm.explainer", module)


def test_explain_happy_path(fixture_client, fake_explainer):
    base = fixture_client.post("/v1/analyse", json={"home": _home("P10001")}).json()
    r = fixture_client.post("/v1/explain", json={"analysis_id": base["analysis_id"], "section": "savings"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"].startswith("savings explanation")
    assert body["check"]["fallback_used"] is True  # no LLM client yet → template


def test_explain_cache_miss(fixture_client, fake_explainer):
    r = fixture_client.post("/v1/explain", json={"analysis_id": "missing", "section": "score"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "analysis_not_found"


def test_explain_bad_section(fixture_client, fake_explainer):
    r = fixture_client.post("/v1/explain", json={"analysis_id": "x", "section": "everything"})
    assert r.status_code == 422


# ---------- methodology ----------
def test_methodology(fixture_client):
    r = fixture_client.get("/v1/methodology")
    assert r.status_code == 200
    body = r.json()
    assert abs(sum(body["weights"].values()) - 1.0) < 1e-9
    assert len(body["retrofit_catalogue"]) == 7
    assert {ef["fuel"] for ef in body["emission_factors"]} == {"electricity", "gas"}
    assert [c["class"] for c in body["classes"]][0] == "highly_efficient"
    _no_nan(r.text)
