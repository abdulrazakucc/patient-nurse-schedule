#!/usr/bin/env python3
"""
Build the site published to GitHub Pages.

A static site cannot check who is asking: every file on GitHub Pages can be
downloaded by anyone. So the site takes one of two shapes, decided by whether
any accounts are supplied (``NEOSTAY_USERS_JSON`` in CI, ``--users-file``
locally):

* **Landing page only** -- no accounts. The public landing page, saying what
  NeoStay does and that access is not open yet; no application code and no data.

* **Sealed application** -- with accounts. Every page and script of the web
  application, with its data published only as ciphertext:

  - the three data bundles in ``frontend/data/`` are gzip-compressed and
    encrypted together under a random 256-bit key with AES-256-GCM
    (``data.sealed``);
  - that key is wrapped once per account with the account's password hash --
    PBKDF2-HMAC-SHA256 of the password, exactly what the reader's browser
    derives when they sign in (``keys.json``). No email address, name, password
    or password hash is published: an account is listed only by a SHA-256
    digest of its email address.

  Every build uses a new key, so an account removed from the users file cannot
  open the next published copy.

The protection is as strong as each password against offline guessing, and
anyone who opened an earlier copy keeps what they saw. See SECURITY.md.

Usage::

    make site                                            # or, by hand:
    python3 scripts/build_pages_site.py --out site
    python3 scripts/build_pages_site.py --users-file instance/access/users.json
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import accounts  # noqa: E402

FRONTEND = ROOT / "frontend"

MAGIC = b"NEOS1"
CONTEXT = "neostay-sealed-v1"
BUNDLES = {
    "NEOSTAY_DATA": "data/neostay-data.js",
    "NEOSTAY_ACUITY": "data/neostay-acuity.js",
    "NEOSTAY_TS": "data/neostay-timeseries.js",
}
SEALED_CONFIG = """/* Written by scripts/build_pages_site.py: this copy opens its data in the
   browser, from data.sealed, with a registered account's password. */
window.NEOSTAY_ACCESS = { mode: "sealed" };
"""
CLOSED_CONFIG = """/* Written by scripts/build_pages_site.py: no accounts were supplied, so this
   copy is the landing page only, with no sign-in form, application or data. */
window.NEOSTAY_ACCESS = { mode: "closed" };
"""
# The landing page and exactly what it needs to render.
LANDING_SOURCES = ("index.html", "styles.css", "favicon.svg", "access.js", "sealed.js")
CLOSED_FILES = frozenset({".nojekyll", "access-config.js", *LANDING_SOURCES})
SEALED_EXTRA = frozenset({".nojekyll", "data.sealed", "keys.json"})
IGNORED_NAMES = frozenset({".DS_Store", "Thumbs.db"})


def read_bundle(name: str, relative: str) -> object:
    """The JSON inside one ``window.NAME = {...};`` data bundle."""
    text = (FRONTEND / relative).read_text(encoding="utf-8").strip()
    prefix = f"window.{name} = "
    if not text.startswith(prefix) or not text.endswith(";"):
        raise SystemExit(f"Unexpected format in frontend/{relative}")
    return json.loads(text[len(prefix) : -1])


def application_files() -> set[str]:
    """Every file of the web application, without its data bundles."""
    return {
        str(path.relative_to(FRONTEND))
        for path in FRONTEND.rglob("*")
        if path.is_file()
        and path.name not in IGNORED_NAMES
        and path.relative_to(FRONTEND).parts[0] != "data"
    }


def account_id(email: str) -> str:
    return hashlib.sha256(f"{CONTEXT}:{email.strip().lower()}".encode()).hexdigest()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def seal(bundle: dict, users: dict[str, accounts.User]) -> tuple[bytes, dict]:
    """Encrypt ``bundle`` under a fresh key, and wrap that key for each account."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    plain = gzip.compress(
        json.dumps(bundle, separators=(",", ":"), ensure_ascii=False).encode(), mtime=0
    )
    key = AESGCM.generate_key(bit_length=256)
    nonce = secrets.token_bytes(12)
    sealed = MAGIC + nonce + AESGCM(key).encrypt(nonce, plain, CONTEXT.encode())

    entries = []
    for user in users.values():
        account = account_id(user.email)
        wrap_nonce = secrets.token_bytes(12)
        entries.append(
            {
                "id": account,
                "salt": _b64(user.salt),
                "iterations": user.iterations,
                "nonce": _b64(wrap_nonce),
                "wrapped": _b64(AESGCM(user.hash).encrypt(wrap_nonce, key, account.encode())),
            }
        )
    keys = {
        "format": "neostay-sealed-keys",
        "version": 1,
        "kdf": "pbkdf2-sha256",
        "iterations": accounts.ITERATIONS,
        "users": sorted(entries, key=lambda entry: entry["id"]),
    }
    return sealed, keys


def open_sealed(sealed: bytes, keys: dict, email: str, password: str) -> dict:
    """Open a sealed copy the way a browser does. Raises on wrong credentials."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    account = account_id(email)
    entry = next((item for item in keys["users"] if item["id"] == account), None)
    if entry is None:
        raise ValueError("No account for that email in this copy")
    wrapping = accounts.hash_password(
        password, base64.b64decode(entry["salt"]), entry["iterations"]
    )
    key = AESGCM(wrapping).decrypt(
        base64.b64decode(entry["nonce"]), base64.b64decode(entry["wrapped"]), account.encode()
    )
    if not sealed.startswith(MAGIC):
        raise ValueError("Not a sealed bundle")
    start = len(MAGIC)
    plain = AESGCM(key).decrypt(sealed[start : start + 12], sealed[start + 12 :], CONTEXT.encode())
    return json.loads(gzip.decompress(plain))


def plaintext_markers(globals_: dict, users: dict[str, accounts.User]) -> list[bytes]:
    """Strings that must never appear outside the ciphertext."""
    tool = globals_["NEOSTAY_ACUITY"]
    markers = [c["label"] for c in tool["levels_of_care"]["general"]["criteria"][:8]]
    markers += list(globals_["NEOSTAY_TS"]["series"])[:8]
    # Names are never written by the build, and people named on the site (the
    # project leads) may well hold accounts, so names are not markers.
    markers += [user.email for user in users.values()]
    markers += [_b64(user.hash) for user in users.values()]
    return [marker.encode() for marker in markers]


def _files(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def build(out_dir: Path, users: dict[str, accounts.User] | None = None) -> dict:
    """Write the Pages site to ``out_dir`` and return what was published."""
    users = users or {}
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    # Without this, GitHub Pages runs the output through Jekyll.
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    if not users:
        for name in LANDING_SOURCES:
            shutil.copyfile(FRONTEND / name, out_dir / name)
        (out_dir / "access-config.js").write_text(CLOSED_CONFIG, encoding="utf-8")
        expected = set(CLOSED_FILES)
    else:
        app_files = application_files()
        for relative in sorted(app_files):
            target = out_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FRONTEND / relative, target)
        (out_dir / "access-config.js").write_text(SEALED_CONFIG, encoding="utf-8")
        globals_ = {name: read_bundle(name, relative) for name, relative in BUNDLES.items()}
        bundle = {
            "format": "neostay-sealed-bundle",
            "version": 1,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "globals": globals_,
        }
        ciphertext, keys = seal(bundle, users)
        (out_dir / "data.sealed").write_bytes(ciphertext)
        (out_dir / "keys.json").write_text(json.dumps(keys, indent=1), encoding="utf-8")
        expected = app_files | SEALED_EXTRA

    written = _files(out_dir)
    if written != expected:
        raise SystemExit(f"Refusing to publish unexpected files: {sorted(written ^ expected)}")
    if users:
        # Defence in depth: nothing readable from the data, and no identity,
        # may appear outside the ciphertext.
        markers = plaintext_markers(globals_, users)
        for name in written - {"data.sealed"}:
            content = (out_dir / name).read_bytes()
            if any(marker in content for marker in markers):
                raise SystemExit(f"Refusing to publish: {name} contains readable data or identities")
    return {"sealed": bool(users), "accounts": len(users), "files": sorted(written)}


_EMAILS = re.compile(r"[^@\s\"'(]+@[^@\s\"')]+")
_ADVICE = "Paste everything `make user-export` prints, from the first { to the last }."


def secret_hints(text: str) -> str:
    """What is visibly wrong with a secret, without repeating any of its content."""
    hints = [f"{len(text)} characters"]
    if "gbd-users" in text:
        hints.append("it looks like a users file from another application (gbd-users), not NeoStay")
    elif "neostay-users" not in text:
        hints.append('it does not contain "neostay-users", so it is not the output of `make user-export`')
    if any(quote in text for quote in "“”‘’"):
        hints.append("it contains curly quotes, which JSON does not allow")
    return "; ".join(hints)


def users_from_secret(text: str) -> dict[str, accounts.User]:
    """Accounts from the NEOSTAY_USERS_JSON secret.

    Tolerates text pasted around the JSON -- such as the warning line that
    ``make user-export`` prints above it -- and explains any other problem.
    """
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise SystemExit(
            f"NEOSTAY_USERS_JSON does not contain a NeoStay users file ({secret_hints(text)}). {_ADVICE}"
        )
    try:
        users = accounts.parse_users(text[start : end + 1])
    except (ValueError, KeyError, TypeError) as exc:
        raise SystemExit(
            f"NEOSTAY_USERS_JSON is not a valid NeoStay users file: {exc} ({secret_hints(text)}). {_ADVICE}"
        ) from exc
    if not users:
        raise SystemExit("NEOSTAY_USERS_JSON contains no accounts. Add one with `make user-add`.")
    return users


def github_error(title: str, message: str) -> None:
    """Show a problem on the workflow run page, where it is readable without
    signing in to GitHub. Email addresses are never repeated there."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    clean = _EMAILS.sub("<email address>", message)
    clean = clean.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::error title={title}::{clean}")


def github_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the NeoStay site for GitHub Pages.")
    parser.add_argument("--out", type=Path, default=ROOT / "site", help="Output directory")
    parser.add_argument(
        "--users-file",
        type=Path,
        default=None,
        help="Seal the application for these accounts (default: the NEOSTAY_USERS_JSON variable)",
    )
    parser.add_argument(
        "--landing-if-secret-invalid",
        action="store_true",
        help="If NEOSTAY_USERS_JSON cannot be read, publish the landing page only instead of failing",
    )
    args = parser.parse_args()

    users_json = os.environ.get("NEOSTAY_USERS_JSON", "").strip()
    if users_json:
        try:
            users = users_from_secret(users_json)
        except SystemExit as problem:
            if not args.landing_if_secret_invalid:
                raise
            print(problem, file=sys.stderr)
            github_error("NEOSTAY_USERS_JSON could not be read", str(problem))
            github_output("secret_invalid", "true")
            users = {}
    elif args.users_file:
        users = accounts.load_users(args.users_file)
    else:
        users = {}
    result = build(args.out, users)
    if result["sealed"]:
        print(
            f"Site written to {args.out}: the application, sealed for "
            f"{result['accounts']} account(s)."
        )
    else:
        print(f"Site written to {args.out}: landing page only (no accounts supplied).")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as stop:
        if isinstance(stop.code, str):
            github_error("GitHub Pages build failed", stop.code)
        raise
