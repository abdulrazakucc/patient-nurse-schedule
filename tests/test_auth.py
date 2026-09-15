"""
Sign-in tests for the server.

Three promises: passwords are stored and checked the standard way (so the same
credentials also open the sealed GitHub Pages copy); data is unreachable without
a valid session; and sessions end when an account is removed or its password
changes.
"""
from __future__ import annotations

import io
import stat

import pytest
from fastapi.testclient import TestClient

from app import accounts, auth, config

EMAIL = "charge.nurse@hospital.example"
PASSWORD = "correct horse battery staple"

PROTECTED_GET = [
    "/api/meta",
    "/api/analytics",
    "/api/acuity-tool",
    "/api/ts/summary",
    "/data/neostay-data.js",
    "/data/neostay-acuity.js",
    "/data/neostay-timeseries.js",
]


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    # The floor the users file accepts, so tests stay quick without weakening it.
    monkeypatch.setattr(accounts, "ITERATIONS", accounts.MIN_ITERATIONS)


@pytest.fixture()
def users_file(tmp_path, monkeypatch):
    path = tmp_path / "access" / "users.json"
    monkeypatch.setattr(config, "USERS_FILE", path)
    accounts.add_user(EMAIL, PASSWORD, "Charge Nurse", path)
    return path


@pytest.fixture()
def secure_client(users_file, monkeypatch):
    monkeypatch.setattr(config, "AUTH_MODE", "password")
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 40)
    monkeypatch.setattr(auth, "limiter", auth.LoginLimiter())
    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client


def _sign_in(client: TestClient, email: str = EMAIL, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


class TestPasswords:
    def test_hashing_is_standard_pbkdf2_sha256(self) -> None:
        """RFC 6070-style vector: what WebCrypto derives in the browser."""
        expected = "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b"
        assert accounts.hash_password("password", b"salt", 1).hex() == expected

    def test_equivalent_unicode_passwords_hash_identically(self) -> None:
        salt = b"s" * 16
        # U+FB01 is the "fi" ligature some keyboards and autocorrect produce.
        assert accounts.hash_password("ﬁle cabinet 2026", salt, 1) == accounts.hash_password(
            "file cabinet 2026", salt, 1
        )

    @pytest.mark.parametrize("weak", ["short", " padded password ", EMAIL])
    def test_weak_passwords_are_refused(self, tmp_path, weak) -> None:
        with pytest.raises(ValueError):
            accounts.add_user(EMAIL, weak, path=tmp_path / "users.json")

    def test_users_file_is_private_and_holds_no_password(self, users_file) -> None:
        assert stat.S_IMODE(users_file.stat().st_mode) == 0o600
        text = users_file.read_text()
        assert PASSWORD not in text and EMAIL in text

    def test_authentication(self, users_file) -> None:
        assert accounts.authenticate(EMAIL, PASSWORD).email == EMAIL
        assert accounts.authenticate(EMAIL.upper(), PASSWORD).email == EMAIL
        assert accounts.authenticate(EMAIL, PASSWORD + "!") is None
        assert accounts.authenticate("nobody@hospital.example", PASSWORD) is None
        assert accounts.authenticate("not an email", PASSWORD) is None

    def test_a_new_password_replaces_the_old_and_keeps_the_account(self, users_file) -> None:
        before = accounts.load_users()[EMAIL]
        after = accounts.add_user(EMAIL, "a different long password")
        assert after.created_at == before.created_at and after.name == "Charge Nurse"
        assert accounts.password_version(after) != accounts.password_version(before)
        assert accounts.authenticate(EMAIL, PASSWORD) is None

    def test_weak_entries_in_the_file_are_rejected(self, users_file) -> None:
        text = users_file.read_text().replace(
            f'"iterations": {accounts.MIN_ITERATIONS}', '"iterations": 1000'
        )
        with pytest.raises(ValueError, match="Weak"):
            accounts.parse_users(text)


class TestSessionTokens:
    def test_round_trip_tamper_and_expiry(self, users_file, monkeypatch) -> None:
        monkeypatch.setattr(config, "SESSION_SECRET", "k" * 40)
        user = accounts.load_users()[EMAIL]
        token = auth.issue_token(user, now=1_000_000)
        assert auth.read_token(token, now=1_000_001)["sub"] == EMAIL
        assert auth.read_token(token[:-2] + "xx", now=1_000_001) is None
        assert auth.read_token(token, now=1_000_000 + config.SESSION_HOURS * 3600 + 1) is None
        monkeypatch.setattr(config, "SESSION_SECRET", "z" * 40)
        assert auth.read_token(token, now=1_000_001) is None, "a new secret ends every session"


class TestSignIn:
    @pytest.mark.parametrize("path", PROTECTED_GET)
    def test_data_and_api_need_a_session(self, secure_client, path) -> None:
        assert secure_client.get(path).status_code == 401

    def test_calculations_need_a_session(self, secure_client) -> None:
        body = {"weight_g": 900, "ga_weeks": 27}
        assert secure_client.post("/api/predict", json=body).status_code == 401
        assert secure_client.post("/api/schedule", json={"infants": [body]}).status_code == 401

    @pytest.mark.parametrize(
        "path", ["/", "/index.html", "/schedule.html", "/access.js", "/styles.css", "/api/health"]
    )
    def test_pages_and_health_stay_public(self, secure_client, path) -> None:
        assert secure_client.get(path).status_code == 200

    def test_session_status_is_public(self, secure_client) -> None:
        assert secure_client.get("/api/auth/session").json() == {
            "authenticated": False,
            "mode": "password",
            "email": None,
            "name": None,
        }

    def test_signing_in_opens_the_data(self, secure_client) -> None:
        response = _sign_in(secure_client)
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        for path in PROTECTED_GET:
            assert secure_client.get(path).status_code == 200, path
        session = secure_client.get("/api/auth/session").json()
        assert session["authenticated"] and session["email"] == EMAIL

    def test_data_responses_are_not_cached(self, secure_client) -> None:
        _sign_in(secure_client)
        response = secure_client.get("/data/neostay-data.js")
        assert response.headers["cache-control"] == "no-store"

    def test_wrong_password_and_unknown_email_get_the_same_answer(self, secure_client) -> None:
        wrong = _sign_in(secure_client, password="not the password at all")
        unknown = _sign_in(secure_client, email="nobody@hospital.example")
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json() == {"detail": "Email or password is incorrect."}

    def test_signing_out_ends_the_session(self, secure_client) -> None:
        _sign_in(secure_client)
        assert secure_client.post("/api/auth/logout").status_code == 204
        secure_client.cookies.clear()
        assert secure_client.get("/data/neostay-data.js").status_code == 401

    def test_removing_an_account_ends_its_session_immediately(self, secure_client) -> None:
        _sign_in(secure_client)
        accounts.remove_user(EMAIL)
        assert secure_client.get("/api/meta").status_code == 401

    def test_changing_a_password_ends_existing_sessions(self, secure_client) -> None:
        _sign_in(secure_client)
        accounts.add_user(EMAIL, "a brand new long password")
        assert secure_client.get("/api/meta").status_code == 401

    def test_a_forged_cookie_is_refused(self, secure_client) -> None:
        secure_client.cookies.set(auth.COOKIE, "v1.eyJzdWIiOiJ4In0.forged")
        assert secure_client.get("/api/meta").status_code == 401

    def test_repeated_failures_are_slowed_down(self, secure_client) -> None:
        for _ in range(auth.LoginLimiter.PER_ACCOUNT):
            assert _sign_in(secure_client, password="wrong password guess").status_code == 401
        blocked = _sign_in(secure_client)
        assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0

    def test_sign_in_posted_from_another_site_is_refused(self, secure_client) -> None:
        response = secure_client.post(
            "/api/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
            headers={"Origin": "https://elsewhere.example"},
        )
        assert response.status_code == 403

    def test_password_sign_in_is_unavailable_in_other_modes(self, secure_client, monkeypatch):
        monkeypatch.setattr(config, "AUTH_MODE", "off")
        assert _sign_in(secure_client).status_code == 404


class TestSecurityHeaders:
    def test_pages_carry_a_content_security_policy(self, secure_client) -> None:
        response = secure_client.get("/schedule.html")
        policy = response.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in policy and "script-src 'self'" in policy
        assert response.headers["x-frame-options"] == "DENY"

    def test_api_docs_are_hidden_by_default(self, secure_client) -> None:
        assert secure_client.get("/docs").status_code in {401, 404}
        assert secure_client.get("/openapi.json").status_code in {401, 404}

    def test_unknown_host_names_are_refused(self, secure_client) -> None:
        assert secure_client.get("/", headers={"Host": "attacker.example"}).status_code == 400


class TestProxyMode:
    def test_requests_without_the_proxy_secret_are_refused(self, monkeypatch) -> None:
        from app.main import create_app

        monkeypatch.setattr(config, "AUTH_MODE", "proxy")
        monkeypatch.setattr(config, "PROXY_SECRET", "p" * 40)
        with TestClient(create_app()) as client:
            assert client.get("/data/neostay-data.js").status_code == 401
            assert client.get("/").status_code == 401
            assert client.get("/api/health").status_code == 200
            headers = {"X-NeoStay-Proxy-Secret": "p" * 40, "X-Forwarded-User": "sso-user"}
            assert client.get("/data/neostay-data.js", headers=headers).status_code == 200
            assert client.get("/api/auth/session", headers=headers).json()["email"] == "sso-user"


class TestProductionSafety:
    def test_production_refuses_to_run_without_sign_in(self, monkeypatch) -> None:
        from app.main import create_app

        monkeypatch.setattr(config, "ENVIRONMENT", "production")
        monkeypatch.setattr(config, "AUTH_MODE", "off")
        with pytest.raises(RuntimeError, match="requires sign-in"):
            create_app()

    def test_production_password_mode_needs_a_strong_session_secret(self, monkeypatch):
        from app.main import create_app

        monkeypatch.setattr(config, "ENVIRONMENT", "production")
        monkeypatch.setattr(config, "AUTH_MODE", "password")
        monkeypatch.setattr(config, "SESSION_SECRET", "short")
        with pytest.raises(RuntimeError, match="session secret"):
            create_app()
        monkeypatch.setattr(config, "SESSION_SECRET", "x" * 40)
        assert create_app()

    def test_production_cookies_are_secure(self, secure_client, monkeypatch) -> None:
        monkeypatch.setattr(config, "ENVIRONMENT", "production")
        assert "secure" in _sign_in(secure_client).headers["set-cookie"].lower()


class TestCommandLine:
    def test_add_list_export_and_remove(self, tmp_path, monkeypatch, capsys) -> None:
        path = tmp_path / "users.json"
        monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
        args = ["--file", str(path)]
        assert accounts.main([*args, "add", EMAIL, "--name", "Charge Nurse", "--password-stdin"]) == 0
        assert accounts.main([*args, "list"]) == 0
        assert EMAIL in capsys.readouterr().out
        assert accounts.main([*args, "export"]) == 0
        exported = capsys.readouterr().out
        assert accounts.parse_users(exported)[EMAIL].name == "Charge Nurse"
        assert PASSWORD not in exported
        assert accounts.main([*args, "remove", EMAIL]) == 0
        assert accounts.main([*args, "remove", EMAIL]) == 1
