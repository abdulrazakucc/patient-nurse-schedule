"""
User accounts: who may sign in to NeoStay, and how their passwords are checked.

Accounts live in one JSON file (``NEOSTAY_USERS_FILE``, default
``instance/access/users.json``). It is git-ignored, never copied into an image,
and written with owner-only permissions. The same file serves both deployments:

* a hospital server checks passwords against it on every sign-in;
* the GitHub Pages build uses it to seal the data, so that only these
  credentials can open the published copy (``scripts/build_pages_site.py``).

Passwords are stored as PBKDF2-HMAC-SHA256 hashes -- 600,000 iterations and a
random 16-byte salt per account. PBKDF2 rather than Argon2 because browsers
implement it natively: on GitHub Pages the same derivation, run in the reader's
browser, produces the key that opens the data. A stored hash is therefore a
secret. Treat the users file like any password database.

Usage (from the ``backend/`` directory, or through ``make``):

.. code-block:: console

    python -m app.accounts add someone@hospital.org --name "Full Name"
    python -m app.accounts list
    python -m app.accounts remove someone@hospital.org
    python -m app.accounts export      # for the NEOSTAY_USERS_JSON GitHub secret
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config

FORMAT = "neostay-users"
VERSION = 1
KDF = "pbkdf2-sha256"
ITERATIONS = 600_000
MIN_ITERATIONS = 100_000
SALT_BYTES = 16
HASH_BYTES = 32
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class User:
    email: str
    name: str
    salt: bytes
    iterations: int
    hash: bytes
    created_at: str


def normalise_email(email: str) -> str:
    """Lower-case and trim an address, refusing anything that is not one."""
    clean = (email or "").strip().lower()
    if not _EMAIL.match(clean) or len(clean) > 254:
        raise ValueError(f"Not a valid email address: {email!r}")
    return clean


def _password_bytes(password: str) -> bytes:
    # NFKC in both Python and the browser, so the same password typed on any
    # keyboard produces the same bytes -- and therefore the same key.
    return unicodedata.normalize("NFKC", password).encode("utf-8")


def password_problems(password: str, email: str = "") -> list[str]:
    """Reasons a password is not acceptable; empty when it is."""
    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"Use at most {MAX_PASSWORD_LENGTH} characters.")
    if password.strip() != password or not password.strip():
        problems.append("Do not start or end the password with spaces.")
    if email and password.strip().lower() == email.strip().lower():
        problems.append("The password must not be the email address.")
    return problems


def hash_password(password: str, salt: bytes, iterations: int | None = None) -> bytes:
    """PBKDF2-HMAC-SHA256 -- byte-for-byte what WebCrypto derives in the browser."""
    rounds = iterations or ITERATIONS
    return hashlib.pbkdf2_hmac("sha256", _password_bytes(password), salt, rounds, HASH_BYTES)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


# ------------------------------------------------------------------ storage ----

_cache: dict[str, tuple[tuple[int, int, int], dict[str, User]]] = {}


def parse_users(text: str) -> dict[str, User]:
    """Read the users file format. Raises ValueError on anything unexpected."""
    data = json.loads(text)
    if data.get("format") != FORMAT or data.get("version") != VERSION or data.get("kdf") != KDF:
        raise ValueError("Not a version 1 neostay-users file")
    users = {}
    for item in data.get("users", []):
        user = User(
            email=normalise_email(item["email"]),
            name=str(item.get("name", "")),
            salt=_unb64(item["salt"]),
            iterations=int(item["iterations"]),
            hash=_unb64(item["hash"]),
            created_at=str(item.get("created_at", "")),
        )
        if (
            len(user.salt) < SALT_BYTES
            or len(user.hash) != HASH_BYTES
            or user.iterations < MIN_ITERATIONS
        ):
            raise ValueError(f"Weak or malformed entry for {user.email}")
        users[user.email] = user
    return users


def load_users(path: Path | None = None) -> dict[str, User]:
    """All accounts, keyed by email. A missing file means no accounts.

    Cached by modification time, so it is cheap to call on every request and a
    change -- a removed account, a new password -- takes effect on the next one.
    """
    path = Path(path or config.USERS_FILE)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {}
    # A save replaces the file, so the inode changes even within one clock tick.
    key = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
    cached = _cache.get(str(path))
    if cached and cached[0] == key:
        return cached[1]
    users = parse_users(path.read_text(encoding="utf-8"))
    _cache[str(path)] = (key, users)
    return users


def dump_users(users: dict[str, User]) -> str:
    return json.dumps(
        {
            "format": FORMAT,
            "version": VERSION,
            "kdf": KDF,
            "users": [
                {
                    "email": u.email,
                    "name": u.name,
                    "salt": _b64(u.salt),
                    "iterations": u.iterations,
                    "hash": _b64(u.hash),
                    "created_at": u.created_at,
                }
                for u in sorted(users.values(), key=lambda u: u.email)
            ],
        },
        indent=2,
    )


def save_users(users: dict[str, User], path: Path | None = None) -> Path:
    """Write atomically, readable by the owner only."""
    path = Path(path or config.USERS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(dump_users(users) + "\n")
    os.replace(temp, path)
    return path


def add_user(email: str, password: str, name: str = "", path: Path | None = None) -> User:
    """Create an account, or set a new password for an existing one."""
    email = normalise_email(email)
    problems = password_problems(password, email)
    if problems:
        raise ValueError(" ".join(problems))
    users = dict(load_users(path))
    salt = secrets.token_bytes(SALT_BYTES)
    previous = users.get(email)
    user = User(
        email=email,
        name=name.strip() or (previous.name if previous else ""),
        salt=salt,
        iterations=ITERATIONS,
        hash=hash_password(password, salt, ITERATIONS),
        created_at=previous.created_at
        if previous
        else datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    users[email] = user
    save_users(users, path)
    return user


def remove_user(email: str, path: Path | None = None) -> bool:
    email = normalise_email(email)
    users = dict(load_users(path))
    if users.pop(email, None) is None:
        return False
    save_users(users, path)
    return True


# A fixed decoy, so that checking an unknown email costs the same as a real one
# and response timing does not reveal which addresses have accounts.
_DECOY_SALT = hashlib.sha256(b"neostay-accounts-decoy").digest()[:SALT_BYTES]


def authenticate(email: str, password: str, path: Path | None = None) -> User | None:
    """The account these credentials belong to, or None."""
    try:
        email = normalise_email(email)
    except ValueError:
        email = ""
    if not password or len(password) > MAX_PASSWORD_LENGTH:
        return None
    user = load_users(path).get(email)
    if user is None:
        hash_password(password, _DECOY_SALT)
        return None
    candidate = hash_password(password, user.salt, user.iterations)
    return user if hmac.compare_digest(candidate, user.hash) else None


def password_version(user: User) -> str:
    """Changes whenever the password does, so old sessions stop working."""
    return hmac.new(user.hash, b"neostay-session-version", hashlib.sha256).hexdigest()[:16]


# ---------------------------------------------------------------------- CLI ----


def _read_password(email: str, from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    while True:
        first = getpass.getpass(
            f"Password for {email} (at least {MIN_PASSWORD_LENGTH} characters): "
        )
        problems = password_problems(first, email)
        if problems:
            print(" ".join(problems), file=sys.stderr)
            continue
        if getpass.getpass("Repeat the password: ") != first:
            print("The passwords did not match. Try again.", file=sys.stderr)
            continue
        return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage who can sign in to NeoStay.")
    parser.add_argument(
        "--file", type=Path, default=None, help="Users file (default: NEOSTAY_USERS_FILE)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="Create an account or set a new password")
    add.add_argument("email")
    add.add_argument("--name", default="")
    add.add_argument("--password-stdin", action="store_true", help="Read the password from stdin")
    remove = commands.add_parser("remove", help="Remove an account")
    remove.add_argument("email")
    commands.add_parser("list", help="List accounts")
    commands.add_parser("export", help="Print the users file, for the GitHub Pages secret")
    args = parser.parse_args(argv)
    path = Path(args.file or config.USERS_FILE)

    try:
        if args.command == "add":
            email = normalise_email(args.email)
            user = add_user(email, _read_password(email, args.password_stdin), args.name, path)
            print(f"Saved {user.email} to {path}. A running server applies this at once.")
            print("GitHub Pages copy: update the NEOSTAY_USERS_JSON secret (make user-export).")
        elif args.command == "remove":
            if not remove_user(args.email, path):
                print(f"No account for {args.email}", file=sys.stderr)
                return 1
            print(f"Removed {args.email}. Their server sessions have ended.")
            print("GitHub Pages copy: update NEOSTAY_USERS_JSON so the next build locks them out.")
        elif args.command == "list":
            users = load_users(path)
            if not users:
                print(
                    f"No accounts in {path}. Create one with: "
                    "make user-add EMAIL=someone@hospital.org"
                )
            for user in users.values():
                print(f"{user.email:40} {user.name:24} since {user.created_at[:10]}")
        else:
            if not load_users(path):
                print(f"No accounts in {path}.", file=sys.stderr)
                return 1
            print(
                "This contains password hashes: paste it only into a GitHub secret.",
                file=sys.stderr,
            )
            print(path.read_text(encoding="utf-8"), end="")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
