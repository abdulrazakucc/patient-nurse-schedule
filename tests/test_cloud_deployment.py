"""
Deploying NeoStay without a writable disk.

Serverless container hosts (Cloud Run, App Runner, Container Apps) give a
container no storage and choose its port. These tests hold NeoStay to that:
accounts can arrive as an environment secret, they are then read-only, and the
start-up script listens on whatever port the platform sets.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import accounts, auth, config

ROOT = Path(__file__).resolve().parent.parent
EMAIL = "cloud.admin@hospital.example"
PASSWORD = "a long cloud password"


@pytest.fixture()
def supplied_accounts(tmp_path, monkeypatch):
    """One account, handed in the way a platform hands in a secret."""
    monkeypatch.setattr(accounts, "ITERATIONS", accounts.MIN_ITERATIONS)
    path = tmp_path / "users.json"
    accounts.add_user(EMAIL, PASSWORD, "Cloud Admin", path)
    monkeypatch.setattr(config, "USERS_JSON", path.read_text())
    monkeypatch.setattr(config, "USERS_FILE", tmp_path / "does-not-exist.json")
    return path


class TestAccountsFromTheEnvironment:
    def test_accounts_are_read_without_any_file(self, supplied_accounts) -> None:
        users = accounts.load_users()
        assert set(users) == {EMAIL}
        assert accounts.read_only() is True
        assert accounts.authenticate(EMAIL, PASSWORD).email == EMAIL

    def test_a_file_still_wins_when_one_is_named(self, supplied_accounts, tmp_path) -> None:
        other = tmp_path / "other.json"
        accounts.add_user("other@hospital.example", PASSWORD, "Other", other)
        assert set(accounts.load_users(other)) == {"other@hospital.example"}

    def test_editing_accounts_is_refused_and_explains_why(self, supplied_accounts) -> None:
        with pytest.raises(ValueError, match="NEOSTAY_USERS_JSON"):
            accounts.add_user("new@hospital.example", PASSWORD)

    def test_signing_in_works_with_no_writable_storage(self, supplied_accounts, monkeypatch) -> None:
        monkeypatch.setattr(config, "AUTH_MODE", "password")
        monkeypatch.setattr(config, "ENVIRONMENT", "production")
        monkeypatch.setattr(config, "SESSION_SECRET", "s" * 40)
        monkeypatch.setattr(auth, "limiter", auth.LoginLimiter())
        from app.main import create_app

        # https, because a production sign-in cookie is marked Secure and a
        # browser (and httpx) will not send it back over plain http.
        with TestClient(create_app(), base_url="https://testserver") as client:
            assert client.get("/data/neostay-data.js").status_code == 401
            assert client.post(
                "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
            ).status_code == 200
            assert client.get("/data/neostay-data.js").status_code == 200


class TestStartUp:
    def test_the_server_listens_on_the_port_the_platform_chooses(self) -> None:
        serve = (ROOT / "deploy" / "serve.sh").read_text()
        assert '--port "${PORT:-8000}"' in serve
        assert "--proxy-headers" in serve

    def test_the_container_starts_without_storage_when_secrets_are_supplied(self) -> None:
        entrypoint = (ROOT / "deploy" / "entrypoint.sh").read_text()
        assert 'if [ -n "${NEOSTAY_USERS_JSON:-}" ]' in entrypoint
        assert (ROOT / "Dockerfile").read_text().count('CMD ["neostay-serve"]') == 1

    def test_kubernetes_manifests_carry_no_real_secret(self) -> None:
        secret = (ROOT / "deploy" / "kubernetes" / "secret.example.yaml").read_text()
        assert '"users": []' in secret and "EXAMPLE ONLY" in secret


class TestSecretsFromThePlatform:
    def test_a_supplied_secret_is_used_when_the_default_file_is_absent(self, monkeypatch, tmp_path) -> None:
        """The image names a secret file; a platform with no disk supplies the value."""
        monkeypatch.setenv("NEOSTAY_SESSION_SECRET_FILE", str(tmp_path / "missing"))
        monkeypatch.setenv("NEOSTAY_SESSION_SECRET", "x" * 40)
        assert config._secret("NEOSTAY_SESSION_SECRET", "NEOSTAY_SESSION_SECRET_FILE") == "x" * 40

    def test_an_unreadable_file_with_no_fallback_still_fails(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("NEOSTAY_SESSION_SECRET_FILE", str(tmp_path / "missing"))
        monkeypatch.delenv("NEOSTAY_SESSION_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="NEOSTAY_SESSION_SECRET_FILE"):
            config._secret("NEOSTAY_SESSION_SECRET", "NEOSTAY_SESSION_SECRET_FILE")

    def test_a_mounted_file_still_wins_over_an_environment_value(self, monkeypatch, tmp_path) -> None:
        path = tmp_path / "secret"
        path.write_text("from-the-file\n")
        monkeypatch.setenv("NEOSTAY_SESSION_SECRET_FILE", str(path))
        monkeypatch.setenv("NEOSTAY_SESSION_SECRET", "from-the-environment")
        assert config._secret("NEOSTAY_SESSION_SECRET", "NEOSTAY_SESSION_SECRET_FILE") == "from-the-file"


class TestAccountCommands:
    def test_adding_or_removing_is_refused_and_points_at_the_platform(self, supplied_accounts, capsys) -> None:
        assert accounts.main(["add", "new@hospital.example"]) == 1
        assert accounts.main(["remove", EMAIL]) == 1
        assert "NEOSTAY_USERS_JSON" in capsys.readouterr().err

    def test_listing_and_exporting_read_the_supplied_accounts(self, supplied_accounts, capsys) -> None:
        assert accounts.main(["list"]) == 0
        assert EMAIL in capsys.readouterr().out
        assert accounts.main(["export"]) == 0
        assert set(accounts.parse_users(capsys.readouterr().out)) == {EMAIL}

    def test_an_explicit_file_is_still_editable(self, supplied_accounts, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(PASSWORD + "\n"))
        target = tmp_path / "explicit.json"
        assert accounts.main(["--file", str(target), "add", "local@hospital.example", "--password-stdin"]) == 0
        assert set(accounts.load_users(target)) == {"local@hospital.example"}
