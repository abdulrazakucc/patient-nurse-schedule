#!/usr/bin/env bash
# Start the NeoStay application locally.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt

echo "NeoStay running at http://127.0.0.1:8000"
cd backend
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
