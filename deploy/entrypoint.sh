#!/bin/sh
# NeoStay container entrypoint: prepare the private state, then start the server.
set -eu

INSTANCE="${NEOSTAY_INSTANCE_DIR:-/srv/instance}"
SECRET="${NEOSTAY_SESSION_SECRET_FILE:-$INSTANCE/session_secret}"
USERS="${NEOSTAY_USERS_FILE:-$INSTANCE/access/users.json}"

if [ ! -w "$INSTANCE" ]; then
  echo "!! $INSTANCE is not writable by this container (running as UID $(id -u))." >&2
  echo "!! Use the named volume from docker-compose.yml, or give UID 10001 write access." >&2
  exit 1
fi

umask 077
mkdir -p "$(dirname "$USERS")"

# The secret that signs sign-in cookies: created once and kept in the volume,
# so people stay signed in across restarts and upgrades.
if [ -z "${NEOSTAY_SESSION_SECRET:-}" ] && [ ! -s "$SECRET" ]; then
  python -c "import secrets; print(secrets.token_urlsafe(48))" > "$SECRET"
  echo "==> Created a session secret in $SECRET"
fi

if [ ! -s "$USERS" ]; then
  echo "==> No accounts yet. Create the first one with:"
  echo "    docker compose exec app python -m app.accounts add someone@hospital.org --name \"Full Name\""
fi

exec "$@"
