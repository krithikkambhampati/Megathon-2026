"""Accounts and login sessions in one SQLite file (GREENHOME_DB, default data/app.sqlite; gitignored).

Passwords: scrypt with a per-user salt (stdlib, no extra package). Sessions: a random token in an httpOnly
cookie; only its SHA-256 is stored, so a leaked database file can't be replayed as a login. Sessions live
SESSION_DAYS and survive API restarts.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION_COOKIE = "ghs_session"
SESSION_DAYS = 30
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
"""


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str


class EmailTaken(Exception):
    pass


def db_path() -> Path:
    raw = os.environ.get("GREENHOME_DB", "data/app.sqlite")
    p = Path(raw)
    return p if p.is_absolute() else REPO_ROOT / p


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, key_hex = stored.split("$")
    except ValueError:
        return False
    key = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(key.hex(), key_hex)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# A dummy hash so a login for an unknown email takes as long as a wrong password (no account probing).
_DUMMY_HASH = hash_password(secrets.token_hex(8))


class AuthStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()  # FastAPI runs sync routes in a thread pool
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def create_user(self, email: str, name: str, password: str) -> User:
        pw = hash_password(password)
        with self._lock:
            try:
                cur = self._db.execute(
                    "INSERT INTO users (email, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (email, name, pw, int(time.time())),
                )
            except sqlite3.IntegrityError as e:
                raise EmailTaken(email) from e
        return User(cur.lastrowid, email, name)

    def authenticate(self, email: str, password: str) -> User | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, email, name, password_hash FROM users WHERE email = ?", (email,)
            ).fetchone()
        if row is None:
            verify_password(password, _DUMMY_HASH)
            return None
        return User(row[0], row[1], row[2]) if verify_password(password, row[3]) else None

    def create_session(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        with self._lock:
            self._db.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (_token_hash(token), user.id, now, now + SESSION_DAYS * 86400),
            )
        return token

    def user_for_token(self, token: str | None) -> User | None:
        if not token:
            return None
        with self._lock:
            row = self._db.execute(
                "SELECT u.id, u.email, u.name FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ? AND s.expires_at > ?",
                (_token_hash(token), int(time.time())),
            ).fetchone()
        return User(*row) if row else None

    def delete_session(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    def purge_expired(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
