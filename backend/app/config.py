"""
Runtime settings for the NeoStay server, resolved once from environment variables.

Every setting is optional in development. Production (``NEOSTAY_ENV=production``)
refuses to start without sign-in and a strong session secret -- see ``main.py``.

================================  ======================================================
``NEOSTAY_ENV``                    ``development`` (default), ``test`` or ``production``.
``NEOSTAY_AUTH_MODE``              ``password`` (default): email and password from the
                                   users file. ``proxy``: an identity-aware reverse
                                   proxy signs people in. ``off``: automated tests only.
``NEOSTAY_INSTANCE_DIR``           Server-private state: accounts and the session
                                   secret. Default: ``<repo>/instance``.
``NEOSTAY_USERS_FILE``             Accounts. Default: ``<instance>/access/users.json``.
``NEOSTAY_SESSION_SECRET_FILE``    File holding the secret that signs session cookies
                                   (preferred), or
``NEOSTAY_SESSION_SECRET``         the secret itself. 32+ characters in production.
``NEOSTAY_SESSION_HOURS``          How long a sign-in lasts. Default: 12.
``NEOSTAY_TRUSTED_HOSTS``          Host names the server answers to, comma-separated.
                                   ``localhost`` and ``127.0.0.1`` are always allowed.
``NEOSTAY_CORS_ORIGINS``           Browser origins allowed to call the API from another
                                   website, comma-separated. Default: none.
``NEOSTAY_AUTH_USER_HEADER``       Proxy mode: header carrying the signed-in user.
``NEOSTAY_PROXY_SECRET_FILE``      Proxy mode: file holding the secret the proxy sends
``NEOSTAY_PROXY_SECRET``           in ``X-NeoStay-Proxy-Secret`` (32+ characters).
``NEOSTAY_EXPOSE_DOCS``            Serve ``/docs`` and ``/openapi.json``. Default: off.
``NEOSTAY_FRONTEND_DIR``           Web application served at ``/``.
                                   Default: ``<repo>/frontend``.
================================  ======================================================
"""
from __future__ import annotations

import os
from pathlib import Path

# The repository root: this file is <root>/backend/app/config.py.
ROOT_DIR = Path(__file__).resolve().parents[2]


def _path(var: str, default: Path) -> Path:
    value = os.environ.get(var, "").strip()
    return Path(value).expanduser() if value else default


FRONTEND_DIR: Path = _path("NEOSTAY_FRONTEND_DIR", ROOT_DIR / "frontend")


def _list(var: str) -> list[str]:
    return [item.strip() for item in os.environ.get(var, "").split(",") if item.strip()]


def _flag(var: str) -> bool:
    return os.environ.get(var, "").strip().lower() in {"1", "true", "yes", "on"}


def _secret(var: str, file_var: str) -> str:
    """Read a secret from a mounted file, falling back to an environment variable."""
    secret_file = os.environ.get(file_var, "").strip()
    if secret_file:
        try:
            return Path(secret_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"Could not read the secret configured by {file_var}") from exc
    return os.environ.get(var, "").strip()


ENVIRONMENT: str = os.environ.get("NEOSTAY_ENV", "development").strip().lower()
AUTH_MODE: str = os.environ.get("NEOSTAY_AUTH_MODE", "password").strip().lower()

INSTANCE_DIR: Path = _path("NEOSTAY_INSTANCE_DIR", ROOT_DIR / "instance")
USERS_FILE: Path = _path("NEOSTAY_USERS_FILE", INSTANCE_DIR / "access" / "users.json")
SESSION_SECRET: str = _secret("NEOSTAY_SESSION_SECRET", "NEOSTAY_SESSION_SECRET_FILE")
try:
    SESSION_HOURS: int = max(1, min(int(os.environ.get("NEOSTAY_SESSION_HOURS", "12")), 24 * 30))
except ValueError:
    SESSION_HOURS = 12

# Health checks and people on the server itself always use these names.
_LOCAL_HOSTS = ["localhost", "127.0.0.1"] + (["testserver"] if ENVIRONMENT != "production" else [])
TRUSTED_HOSTS: list[str] = list(dict.fromkeys([*_list("NEOSTAY_TRUSTED_HOSTS"), *_LOCAL_HOSTS]))
CORS_ORIGINS: list[str] = _list("NEOSTAY_CORS_ORIGINS")

AUTH_USER_HEADER: str = os.environ.get("NEOSTAY_AUTH_USER_HEADER", "X-Forwarded-User").strip()
PROXY_SECRET: str = _secret("NEOSTAY_PROXY_SECRET", "NEOSTAY_PROXY_SECRET_FILE")

EXPOSE_DOCS: bool = _flag("NEOSTAY_EXPOSE_DOCS")
