#!/usr/bin/env bash
# Check a running NeoStay server end to end: public pages, protected data, sign-in.
#
# Usage:
#   NEOSTAY_SMOKE_PASSWORD='the password' scripts/smoke_test.sh BASE_URL EMAIL
#   NEOSTAY_SMOKE_PASSWORD='...' scripts/smoke_test.sh https://neostay.hospital.local someone@hospital.org
#
# Set NEOSTAY_SMOKE_INSECURE=1 to accept a certificate this machine does not trust
# (for example Caddy's internal certificate before IT trusts its root).
set -euo pipefail

usage="Usage: NEOSTAY_SMOKE_PASSWORD=... $0 BASE_URL EMAIL"
BASE="${1:?$usage}"
BASE="${BASE%/}"
EMAIL="${2:?$usage}"
: "${NEOSTAY_SMOKE_PASSWORD:?$usage}"

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
jar="$workdir/cookies"
curl_opts=(--silent --max-time 20 --cookie "$jar" --cookie-jar "$jar")
[ -n "${NEOSTAY_SMOKE_INSECURE:-}" ] && curl_opts+=(--insecure)
failed=0

expect() { # expect STATUS PATH [extra curl arguments...]
  local want=$1 path=$2 got
  shift 2
  got=$(curl "${curl_opts[@]}" --output /dev/null --write-out '%{http_code}' "$@" "$BASE$path")
  if [ "$got" = "$want" ]; then
    printf '    ok   %s  %s\n' "$got" "$path"
  else
    printf '    FAIL %s  %s (expected %s)\n' "$got" "$path" "$want"
    failed=1
  fi
}

echo "==> Smoke testing $BASE"
expect 200 /api/health
expect 200 /
expect 200 /schedule.html
expect 401 /data/neostay-data.js
expect 401 /api/meta

# The password goes through a private file, never onto a command line.
(umask 077 && EMAIL="$EMAIL" python3 -c 'import json, os; print(json.dumps({"email": os.environ["EMAIL"], "password": os.environ["NEOSTAY_SMOKE_PASSWORD"]}))' > "$workdir/login.json")
expect 200 /api/auth/login --header 'Content-Type: application/json' --data-binary "@$workdir/login.json"
expect 200 /data/neostay-data.js
expect 200 /data/neostay-acuity.js
expect 200 /data/neostay-timeseries.js
expect 200 /api/meta
expect 204 /api/auth/logout --request POST
expect 401 /data/neostay-data.js

if [ "$failed" -ne 0 ]; then
  echo "!! Smoke test failed"
  exit 1
fi
echo "==> All checks passed"
