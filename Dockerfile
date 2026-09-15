# NeoStay -- one image serves the web application, its data and the API, all
# behind sign-in. Start it with `docker compose up -d --build` (docs/DEPLOYMENT.md).

FROM python:3.12-slim

# Production by default: the server refuses to start without sign-in and a
# session secret (created on first start by the entrypoint).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NEOSTAY_ENV=production \
    NEOSTAY_AUTH_MODE=password \
    NEOSTAY_INSTANCE_DIR=/srv/instance \
    NEOSTAY_SESSION_SECRET_FILE=/srv/instance/session_secret

WORKDIR /srv/backend

# Dependencies first, in their own layer, so code changes rebuild in seconds.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app/ ./app/
COPY frontend/ /srv/frontend/
COPY datasets/losdata/*.csv /srv/datasets/losdata/
COPY datasets/nurse-skills/*.csv /srv/datasets/nurse-skills/
COPY generated_data/*.csv /srv/generated_data/
COPY deploy/entrypoint.sh /usr/local/bin/neostay-entrypoint

# A non-root user owns only the private state: accounts and the session secret.
RUN chmod 0755 /usr/local/bin/neostay-entrypoint \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin neostay \
    && mkdir -p /srv/instance/access \
    && chown -R neostay:neostay /srv/instance
USER neostay

VOLUME ["/srv/instance"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import sys, urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"

ENTRYPOINT ["neostay-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--proxy-headers"]
