#!/bin/sh
# Start the NeoStay server. Cloud hosts differ only in which port they inject,
# so the port, address and worker count all come from the environment.
#
#   PORT              port to listen on (Cloud Run, App Runner and others set this)
#   WEB_CONCURRENCY   worker processes; keep at 1 unless sign-in rate limiting
#                     has been moved to a shared store (docs/CLOUD.md)
set -eu

exec uvicorn app.main:app \
  --host "${NEOSTAY_HOST:-0.0.0.0}" \
  --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --no-server-header \
  --proxy-headers
