from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.auth import SESSION_COOKIE
from api.main import create_app

ALICE = {"email": "Alice@Example.com", "name": "Alice", "password": "correct horse"}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "app.sqlite"
    monkeypatch.setenv("GREENHOME_DB", str(path))
    return path


def _client() -> TestClient:
    return TestClient(create_app(web=False))  # no `with`: the engine isn't needed for auth


def test_signup_logs_in_and_me_returns_the_user(db) -> None:
    c = _client()
    r = c.post("/v1/auth/signup", json=ALICE)
    assert r.status_code == 201 and r.json()["email"] == "alice@example.com"
    assert "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/v1/auth/me").json()["name"] == "Alice"


def test_session_survives_an_api_restart(db) -> None:
    c = _client()
    c.post("/v1/auth/signup", json=ALICE)
    token = c.cookies[SESSION_COOKIE]
    restarted = _client()  # a fresh app on the same database file
    restarted.cookies.set(SESSION_COOKIE, token)
    assert restarted.get("/v1/auth/me").status_code == 200


def test_login_logout_and_bad_credentials(db) -> None:
    _client().post("/v1/auth/signup", json=ALICE)
    c = _client()
    assert c.get("/v1/auth/me").status_code == 401
    bad = c.post("/v1/auth/login", json={"email": ALICE["email"], "password": "wrong password"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
    unknown = c.post("/v1/auth/login", json={"email": "bob@example.com", "password": "whatever1"})
    assert unknown.status_code == 401
    ok = c.post("/v1/auth/login", json={"email": "alice@example.com", "password": "correct horse"})
    assert ok.is_success
    assert c.get("/v1/auth/me").status_code == 200
    token = c.cookies[SESSION_COOKIE]
    assert c.post("/v1/auth/logout").status_code == 204
    other = _client()
    other.cookies.set(SESSION_COOKIE, token)
    assert other.get("/v1/auth/me").status_code == 401  # the session is gone server-side too


def test_signup_validation_and_duplicates(db) -> None:
    c = _client()
    assert c.post("/v1/auth/signup", json={**ALICE, "password": "short"}).status_code == 422
    assert c.post("/v1/auth/signup", json={**ALICE, "email": "not-an-email"}).status_code == 422
    assert c.post("/v1/auth/signup", json=ALICE).status_code == 201
    dup = _client().post("/v1/auth/signup", json={**ALICE, "email": "alice@EXAMPLE.com"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "email_taken"


def test_password_is_not_stored_in_plain_text(db) -> None:
    _client().post("/v1/auth/signup", json=ALICE)
    assert b"correct horse" not in db.read_bytes()


def test_require_auth_gates_the_data_api_only(db, monkeypatch) -> None:
    monkeypatch.setenv("GREENHOME_REQUIRE_AUTH", "1")
    c = _client()
    assert c.get("/v1/portfolio").status_code == 401
    assert c.get("/v1/labels").status_code == 200
    c.post("/v1/auth/signup", json=ALICE)
    assert c.get("/v1/portfolio").status_code != 401
