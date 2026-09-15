#!/usr/bin/env bash
# Start NeoStay on this computer, with sign-in, at http://127.0.0.1:8000.
# For a hospital server, use Docker instead: see docs/DEPLOYMENT.md.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt

if [ ! -s instance/access/users.json ]; then
  echo "No accounts yet. Create one to sign in:"
  echo "  make user-add EMAIL=you@hospital.org     (or: cd backend && python -m app.accounts add you@hospital.org)"
fi

echo "NeoStay running at http://127.0.0.1:8000"
cd backend
export NEOSTAY_ENV="${NEOSTAY_ENV:-development}"
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
