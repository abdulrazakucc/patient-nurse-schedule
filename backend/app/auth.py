"""
Signing in: sessions, the sign-in routes, and protection against guessing.

``NEOSTAY_AUTH_MODE`` chooses how the server knows who is asking:

* ``password`` (default) -- email and password, checked against the users file
  (``app.accounts``).
* ``proxy`` -- an identity-aware reverse proxy (for example hospital single
  sign-on) authenticates people and passes their identity on.
* ``off`` -- no sign-in, for automated tests only. Production refuses it.

A session is a signed, expiring cookie. It names the user and a fingerprint of
their password, and every request checks both against the users file, so
removing someone or changing their password ends their sessions at once. No
session state is stored on the server, so several server processes stay
consistent as long as they share the session secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import deque
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import accounts, config

COOKIE = "neostay_session"
PUBLIC_API = frozenset({"/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/session"})

_process_secret = secrets.token_bytes(32)


def _key() -> bytes:
    # Development without a configured secret gets a per-process key: sessions
    # simply end when the server restarts. Production refuses to start without one.
    return config.SESSION_SECRET.encode("utf-8") if config.SESSION_SECRET else _process_secret


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(user: accounts.User, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    payload = {
        "sub": user.email,
        "pv": accounts.password_version(user),
        "iat": issued,
        "exp": issued + config.SESSION_HOURS * 3600,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"v1.{body}.{signature}"


def read_token(token: str, now: float | None = None) -> dict | None:
    try:
        version, body, signature = token.split(".")
        expected = _b64(hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest())
        if version != "v1" or not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if payload.get("exp", 0) <= (now if now is not None else time.time()):
        return None
    return payload


def current_user(request: Request) -> accounts.User | None:
    """The signed-in user for a request, re-checked against the users file."""
    payload = read_token(request.cookies.get(COOKIE, ""))
    if not payload:
        return None
    user = accounts.load_users().get(payload.get("sub", ""))
    if user is None or not hmac.compare_digest(
        payload.get("pv", ""), accounts.password_version(user)
    ):
        return None
    return user


class LoginLimiter:
    """Slow password guessing: a few failures per account, more per client.

    Kept in process memory, which suits one server process. Several processes
    need a shared store for the limit to hold across all of them.
    """

    WINDOW = 15 * 60
    PER_ACCOUNT = 5
    PER_CLIENT = 20

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float]:
        entries = self._failures.setdefault(key, deque())
        while entries and entries[0] <= now - self.WINDOW:
            entries.popleft()
        return entries

    def retry_after(self, account: str, client: str, now: float | None = None) -> int:
        now = now if now is not None else time.monotonic()
        with self._lock:
            waits = []
            for key, limit in (
                (f"a:{account}", self.PER_ACCOUNT),
                (f"c:{client}", self.PER_CLIENT),
            ):
                entries = self._recent(key, now)
                if len(entries) >= limit:
                    waits.append(int(entries[0] + self.WINDOW - now) + 1)
            return max(waits, default=0)

    def failed(self, account: str, client: str, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        with self._lock:
            for key in (f"a:{account}", f"c:{client}"):
                self._recent(key, now).append(now)

    def succeeded(self, account: str) -> None:
        with self._lock:
            self._failures.pop(f"a:{account}", None)


limiter = LoginLimiter()
router = APIRouter(prefix="/api/auth", tags=["sign-in"])


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=accounts.MAX_PASSWORD_LENGTH)


class Session(BaseModel):
    authenticated: bool
    mode: str
    email: str | None = None
    name: str | None = None


def _same_origin(request: Request) -> bool:
    """Refuse sign-in attempts posted from another website."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    return urlsplit(origin).netloc == request.headers.get("host", "")


@router.post("/login", response_model=Session)
def login(credentials: Credentials, request: Request, response: Response) -> dict:
    if config.AUTH_MODE != "password":
        raise HTTPException(status_code=404, detail="Password sign-in is not enabled")
    if not _same_origin(request):
        raise HTTPException(status_code=403, detail="Cross-site sign-in is not allowed")

    account = credentials.email.strip().lower()
    client = request.client.host if request.client else "unknown"
    wait = limiter.retry_after(account, client)
    if wait:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Try again in a few minutes.",
            headers={"Retry-After": str(wait)},
        )

    user = accounts.authenticate(credentials.email, credentials.password)
    if user is None:
        limiter.failed(account, client)
        detail = "Email or password is incorrect."
        if config.ENVIRONMENT != "production" and not accounts.load_users():
            detail = (
                "No accounts exist yet. Create one with: make user-add EMAIL=you@hospital.org"
            )
        raise HTTPException(status_code=401, detail=detail)

    limiter.succeeded(account)
    response.set_cookie(
        COOKIE,
        issue_token(user),
        max_age=config.SESSION_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=config.ENVIRONMENT == "production" or request.url.scheme == "https",
        path="/",
    )
    return {"authenticated": True, "mode": "password", "email": user.email, "name": user.name}


@router.post("/logout", status_code=204)
def logout(response: Response) -> Response:
    response.delete_cookie(COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/session", response_model=Session)
def session(request: Request) -> dict:
    """Who is signed in. Always 200, so the page can decide what to show."""
    if config.AUTH_MODE == "off":
        return {"authenticated": True, "mode": "off"}
    if config.AUTH_MODE == "proxy":
        user = request.headers.get(config.AUTH_USER_HEADER, "").strip()
        return {"authenticated": bool(user), "mode": "proxy", "email": user or None}
    user = current_user(request)
    if user is None:
        return {"authenticated": False, "mode": "password"}
    return {"authenticated": True, "mode": "password", "email": user.email, "name": user.name}
