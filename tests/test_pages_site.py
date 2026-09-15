"""
GitHub Pages site tests.

A static site cannot check who is asking. So what GitHub Pages publishes is
either a closed notice, or the application with its data sealed so that only
registered accounts can decrypt it. These tests hold the build to both shapes,
and prove the sealed copy opens -- and only opens -- the way a browser opens it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from app import accounts
from scripts.build_pages_site import (
    BUNDLES,
    CLOSED_FILES,
    SEALED_EXTRA,
    application_files,
    build,
    open_sealed,
    read_bundle,
    users_from_secret,
)

ROOT = Path(__file__).resolve().parent.parent
EMAIL = "charge.nurse@hospital.example"
PASSWORD = "a long unit password"
COLLEAGUE = "manager@hospital.example"
COLLEAGUE_PASSWORD = "another long password"


@pytest.fixture(scope="module", autouse=True)
def fast_hashing():
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(accounts, "ITERATIONS", accounts.MIN_ITERATIONS)
        yield


@pytest.fixture(scope="module")
def users(tmp_path_factory, fast_hashing) -> dict[str, accounts.User]:
    path = tmp_path_factory.mktemp("access") / "users.json"
    accounts.add_user(EMAIL, PASSWORD, "Charge Nurse Example", path)
    accounts.add_user(COLLEAGUE, COLLEAGUE_PASSWORD, "", path)
    return accounts.load_users(path)


@pytest.fixture(scope="module")
def closed_site(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("closed") / "site"
    build(out)
    return out


@pytest.fixture(scope="module")
def sealed_site(tmp_path_factory, users) -> Path:
    out = tmp_path_factory.mktemp("sealed") / "site"
    build(out, users=users)
    return out


def _published(site: Path) -> set[str]:
    return {str(p.relative_to(site)) for p in site.rglob("*") if p.is_file()}


def _open(site: Path, email: str = EMAIL, password: str = PASSWORD) -> dict:
    keys = json.loads((site / "keys.json").read_text())
    return open_sealed((site / "data.sealed").read_bytes(), keys, email, password)


class TestLandingOnly:
    def test_only_the_landing_page_is_published(self, closed_site) -> None:
        assert _published(closed_site) == CLOSED_FILES

    def test_no_application_code_or_data(self, closed_site) -> None:
        assert 'mode: "closed"' in (closed_site / "access-config.js").read_text()
        for name in ("engine.js", "components.js", "schedule.html", "data.sealed", "keys.json"):
            assert not (closed_site / name).exists(), name
        assert not (closed_site / "data").exists()

    def test_the_landing_page_explains_itself(self, closed_site) -> None:
        gate = (closed_site / "access.js").read_text()
        assert "What you can do in NeoStay" in gate and "Access is not open yet" in gate
        assert "Decision support only — not for clinical use" in gate


class TestSealedApplication:
    def test_publishes_the_application_and_ciphertext_only(self, sealed_site) -> None:
        files = _published(sealed_site)
        assert files == application_files() | SEALED_EXTRA
        assert {"index.html", "schedule.html", "engine.js", "access.js", "sealed.js"} <= files
        assert not any(name.startswith("data/") for name in files)

    def test_the_published_pages_open_the_sealed_copy(self, sealed_site) -> None:
        assert 'mode: "sealed"' in (sealed_site / "access-config.js").read_text()

    def test_no_email_name_or_password_hash_is_published(self, sealed_site, users) -> None:
        everything = b"".join((sealed_site / name).read_bytes() for name in _published(sealed_site))
        for user in users.values():
            assert user.email.encode() not in everything
            assert accounts._b64(user.hash).encode() not in everything
        assert b"Charge Nurse Example" not in everything
        entries = json.loads((sealed_site / "keys.json").read_text())["users"]
        assert {frozenset(entry) for entry in entries} == {
            frozenset({"id", "salt", "iterations", "nonce", "wrapped"})
        }

    def test_no_data_appears_outside_the_ciphertext(self, sealed_site) -> None:
        globals_ = _open(sealed_site)["globals"]
        labels = [c["label"] for c in globals_["NEOSTAY_ACUITY"]["levels_of_care"]["general"]["criteria"]]
        infants = list(globals_["NEOSTAY_TS"]["series"])
        for name in _published(sealed_site) - {"data.sealed"}:
            content = (sealed_site / name).read_text(errors="ignore")
            assert not any(label in content for label in labels), name
            assert not any(infant in content for infant in infants), name

    def test_every_account_opens_the_same_data(self, sealed_site) -> None:
        first = _open(sealed_site)
        second = _open(sealed_site, COLLEAGUE, COLLEAGUE_PASSWORD)
        assert first == second

    def test_the_sealed_data_is_exactly_the_committed_bundles(self, sealed_site) -> None:
        globals_ = _open(sealed_site)["globals"]
        assert set(globals_) == set(BUNDLES)
        for name, relative in BUNDLES.items():
            assert globals_[name] == read_bundle(name, relative), name

    def test_a_wrong_password_opens_nothing(self, sealed_site) -> None:
        with pytest.raises(InvalidTag):
            _open(sealed_site, password="not the right password")

    def test_an_unknown_email_opens_nothing(self, sealed_site) -> None:
        with pytest.raises(ValueError):
            _open(sealed_site, email="stranger@hospital.example")

    def test_an_account_removed_before_a_rebuild_is_locked_out(self, tmp_path, users) -> None:
        out = tmp_path / "site"
        build(out, users={EMAIL: users[EMAIL]})
        assert _open(out)["globals"]
        with pytest.raises(ValueError):
            _open(out, COLLEAGUE, COLLEAGUE_PASSWORD)

    def test_an_account_named_like_the_project_leads_still_publishes(self, tmp_path) -> None:
        """Names shown on the site are not identities leaking from the users file."""
        path = tmp_path / "users.json"
        accounts.add_user("lead@hospital.example", PASSWORD, "Dr. Waseem Altaf", path)
        assert build(tmp_path / "site", users=accounts.load_users(path))["sealed"]

    def test_every_build_uses_a_new_key(self, tmp_path, users, sealed_site) -> None:
        other = tmp_path / "again"
        build(other, users=users)
        assert (other / "data.sealed").read_bytes() != (sealed_site / "data.sealed").read_bytes()
        stale_keys = json.loads((sealed_site / "keys.json").read_text())
        with pytest.raises(InvalidTag):
            open_sealed((other / "data.sealed").read_bytes(), stale_keys, EMAIL, PASSWORD)


class TestSecret:
    def test_text_pasted_around_the_users_file_is_ignored(self, users) -> None:
        from app.accounts import dump_users

        pasted = "This contains password hashes: paste it only into a GitHub secret.\n"
        pasted += dump_users(users) + "\n\n"
        assert set(users_from_secret(pasted)) == set(users)

    @pytest.mark.parametrize("bad", ["", "not json at all", '{"format": "something-else"}'])
    def test_a_wrong_secret_is_explained(self, bad) -> None:
        with pytest.raises(SystemExit, match="NEOSTAY_USERS_JSON"):
            users_from_secret(bad)


BROWSER_HARNESS = """
globalThis.isSecureContext = true;
require(process.argv[2]);
const fs = require("fs");
const path = require("path");
const site = process.argv[3];
const fetcher = async (name) => new Response(fs.readFileSync(path.join(site, name)));
const attempt = async (email, password) => {
  try { await NeoSealed.unlock(email, password, fetcher); return "opened"; }
  catch (error) { return error.kind; }
};
(async () => {
  const key = await NeoSealed.unlock(process.argv[4], process.argv[5], fetcher);
  const bundle = await NeoSealed.openBundle(key, fetcher);
  console.log(JSON.stringify({
    title: bundle.globals.NEOSTAY_ACUITY.title,
    series: Object.keys(bundle.globals.NEOSTAY_TS.series).length,
    wrong: await attempt(process.argv[4], "not the right password"),
    unknown: await attempt("stranger@hospital.example", process.argv[5]),
  }));
})().catch((error) => { console.error(error); process.exit(1); });
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js with WebCrypto")
def test_the_browser_code_opens_the_python_sealed_copy(sealed_site, tmp_path) -> None:
    """frontend/sealed.js -- the code browsers run -- against a real build."""
    harness = tmp_path / "harness.js"
    harness.write_text(BROWSER_HARNESS)
    result = subprocess.run(
        ["node", str(harness), str(ROOT / "frontend" / "sealed.js"), str(sealed_site), EMAIL, PASSWORD],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    opened = json.loads(result.stdout)
    assert opened["title"] == read_bundle("NEOSTAY_ACUITY", BUNDLES["NEOSTAY_ACUITY"])["title"]
    assert opened["series"] > 0
    assert opened["wrong"] == opened["unknown"] == "auth"
