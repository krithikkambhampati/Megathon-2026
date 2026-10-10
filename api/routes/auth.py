"""Sign up, log in, log out, current user. The session is an httpOnly cookie (api/auth.py)."""

import os
import re

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, field_validator

from api.auth import SESSION_COOKIE, SESSION_DAYS, AuthStore, EmailTaken, User
from api.errors import APIError

router = APIRouter(prefix="/auth")

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("enter a valid email address")
        return v


class SignupRequest(Credentials):
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter your name")
        return v


class UserOut(BaseModel):
    id: int
    email: str
    name: str


def _store(request: Request) -> AuthStore:
    return request.app.state.auth


def _out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name)


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("GREENHOME_COOKIE_SECURE", "0") == "1",  # set 1 behind HTTPS
        path="/",
    )


def current_user(request: Request) -> User | None:
    return _store(request).user_for_token(request.cookies.get(SESSION_COOKIE))


@router.post("/signup", response_model=UserOut, status_code=201)
def signup(body: SignupRequest, request: Request, response: Response) -> UserOut:
    store = _store(request)
    try:
        user = store.create_user(body.email, body.name, body.password)
    except EmailTaken:
        msg = "An account with this email already exists. Log in instead."
        raise APIError(409, "email_taken", msg) from None
    _set_cookie(response, store.create_session(user))
    return _out(user)


@router.post("/login", response_model=UserOut)
def login(body: Credentials, request: Request, response: Response) -> UserOut:
    store = _store(request)
    user = store.authenticate(body.email, body.password)
    if user is None:
        raise APIError(401, "invalid_credentials", "That email and password don't match an account.")
    _set_cookie(response, store.create_session(user))
    return _out(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> Response:
    _store(request).delete_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(request: Request) -> UserOut:
    user = current_user(request)
    if user is None:
        raise APIError(401, "not_logged_in", "Please log in.")
    return _out(user)
