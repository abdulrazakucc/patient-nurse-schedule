"""
Shared test fixtures.

Settings are read from the environment when ``app.config`` is first imported,
so they are fixed here -- before anything from ``app`` is imported. Tests run
with sign-in switched off by default; ``test_auth.py`` switches it on.
"""
from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

os.environ["NEOSTAY_ENV"] = "test"
os.environ["NEOSTAY_AUTH_MODE"] = "off"
os.environ["NEOSTAY_INSTANCE_DIR"] = tempfile.mkdtemp(prefix="neostay-tests-")
for _var in (
    "NEOSTAY_USERS_FILE",
    "NEOSTAY_SESSION_SECRET",
    "NEOSTAY_SESSION_SECRET_FILE",
    "NEOSTAY_CORS_ORIGINS",
    "NEOSTAY_EXPOSE_DOCS",
    "NEOSTAY_USERS_JSON",
):
    os.environ.pop(_var, None)

sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """The application with sign-in switched off."""
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
