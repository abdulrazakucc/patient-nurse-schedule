# Deploying NeoStay on a hospital server

*For hospital IT, and for the people who will manage NeoStay accounts.*

NeoStay runs as **one Docker container**. Everyone reaches it through a web
browser at an `https://` address, and everyone signs in with an account created
by a NeoStay administrator. Pages, data and API are all behind that sign-in.

> NeoStay is a decision-support prototype for education and research discussion.
> It is not a medical device and must never replace clinical judgment. It holds
> **aggregated statistics only** — no patient-level data is loaded, entered or stored.

---

## 1. What you need

| | |
|---|---|
| **Server** | A Linux server or virtual machine (Ubuntu, RHEL, Debian…). 1 CPU, 1 GB RAM and 2 GB of disk are plenty. On Windows Server, use a Linux VM. |
| **Software** | [Docker Engine](https://docs.docker.com/engine/install/) 24 or newer, with the Compose plugin (`docker compose version`). Git, or a copy of this repository. |
| **A name** | A DNS name for NeoStay, for example `neostay.hospital.local`. |
| **HTTPS** | The hospital's certificate for that name — or the hospital's existing HTTPS reverse proxy. Sign-in only works over `https://`. |
| **Network** | Building the image downloads Python packages and base images. A server without internet access can load an image built elsewhere (section 7). Browsers also fetch web fonts from Google; if that is blocked, NeoStay falls back to system fonts and works normally. |

---

## 2. Install (about 10 minutes)

```bash
git clone https://github.com/abdulrazakucc/patient-nurse-schedule.git neostay
cd neostay
cp .env.example .env
```

Edit `.env` and set, at least:

```bash
NEOSTAY_TRUSTED_HOSTS=neostay.hospital.local    # the name people type
NEOSTAY_SITE_ADDRESS=neostay.hospital.local     # the same name, for HTTPS
NEOSTAY_TLS=internal                            # or the hospital certificate (section 3)
```

Then choose **one** way to provide HTTPS (section 3) and start NeoStay:

```bash
# A: NeoStay serves HTTPS itself, on ports 443 and 80
docker compose --profile https up -d --build

# B: the hospital's existing reverse proxy forwards to NeoStay on 127.0.0.1:8000
docker compose up -d --build
```

Check it is healthy — the `app` service should say `healthy` within a minute:

```bash
docker compose ps
```

Create the first account. The password is typed at a hidden prompt, twice, and
must be at least 12 characters:

```bash
docker compose exec app python -m app.accounts add first.admin@hospital.org --name "First Admin"
```

Finally, check everything end to end from the server:

```bash
NEOSTAY_SMOKE_PASSWORD='that password' scripts/smoke_test.sh https://neostay.hospital.local first.admin@hospital.org
```

Every line should say `ok`. Open `https://neostay.hospital.local` in a browser
and sign in.

---

## 3. HTTPS

Browsers only keep the NeoStay sign-in on an `https://` address. Pick one option.

### Option A — NeoStay's bundled HTTPS proxy (Caddy)

Start with `docker compose --profile https up -d --build`.

* **With the hospital's certificate (recommended).** Copy the certificate
  (including any intermediate certificates) and its private key into
  `deploy/certs/` as `neostay.crt` and `neostay.key`, and set in `.env`:

  ```bash
  NEOSTAY_TLS=/certs/neostay.crt /certs/neostay.key
  ```

* **With Caddy's internal certificate.** `NEOSTAY_TLS=internal` needs no
  certificate files, but browsers warn until computers trust Caddy's root
  certificate. Export it and distribute it through Group Policy or your device
  management:

  ```bash
  docker compose cp https:/data/caddy/pki/authorities/local/root.crt ./neostay-root-ca.crt
  ```

If ports 443 or 80 are already in use, set `NEOSTAY_HTTPS_PORT` and
`NEOSTAY_HTTP_PORT` in `.env`.

### Option B — the hospital's existing reverse proxy

Start with `docker compose up -d --build`. NeoStay listens on `127.0.0.1:8000`
of the server. Point the hospital proxy at it, and have the proxy pass the
original `Host` header and the `https` scheme. An nginx example:

```nginx
server {
    listen 443 ssl;
    server_name neostay.hospital.local;
    ssl_certificate     /etc/ssl/certs/neostay.crt;
    ssl_certificate_key /etc/ssl/private/neostay.key;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Forwarded-For   $remote_addr;
        proxy_set_header   X-Forwarded-Proto https;
    }
}
```

If the proxy runs on a **different machine**, set `NEOSTAY_BIND_ADDRESS=0.0.0.0`,
allow only the proxy through the server's firewall to port 8000, and set
`NEOSTAY_FORWARDED_ALLOW_IPS` to the proxy's IP address.

---

## 4. Managing who can sign in

*For NeoStay administrators. Run these on the server, in the `neostay` folder.*

| To… | Run |
|---|---|
| Add a person | `docker compose exec app python -m app.accounts add name@hospital.org --name "Full Name"` |
| Reset a forgotten password | the same command again — it sets a new password and keeps the account |
| Remove a person | `docker compose exec app python -m app.accounts remove name@hospital.org` |
| See who has access | `docker compose exec app python -m app.accounts list` |

* Changes take effect **immediately** — no restart. Removing an account or
  resetting its password signs that person out everywhere at once.
* Passwords must be at least 12 characters. Give each person their own account,
  and pass on passwords in person or by phone — not in the same email as the address.
* A sign-in lasts 12 hours (`NEOSTAY_SESSION_HOURS` in `.env`).
* After 5 wrong passwords in 15 minutes, an account is paused for the rest of
  those 15 minutes. Waiting — or resetting the password — resolves it.
* Passwords cannot be recovered, only reset.

If `make` is installed on the server, `make docker-user-add EMAIL=... NAME="..."`
and `make docker-user-list` are shortcuts for the same commands.

### Hospital single sign-on (optional)

Instead of NeoStay passwords, an identity-aware reverse proxy can sign people in
with hospital credentials. The proxy must authenticate each request, **remove**
any incoming `X-Forwarded-User` and `X-NeoStay-Proxy-Secret` headers, then set
both itself: the user's identity, and a shared secret of at least 32 characters.
Create `docker-compose.override.yml`:

```yaml
services:
  app:
    environment:
      NEOSTAY_AUTH_MODE: proxy
      NEOSTAY_PROXY_SECRET_FILE: /run/secrets/neostay_proxy_secret
    secrets: [neostay_proxy_secret]
secrets:
  neostay_proxy_secret:
    file: ./secrets/neostay_proxy_secret   # readable by the container (chmod 644, in a chmod 700 folder)
```

In this mode NeoStay refuses every request that does not carry the secret, and
the account commands above are not used.

---

## 5. Everyday operation

| Task | Command |
|---|---|
| Status | `docker compose ps` |
| Logs | `docker compose logs -f app` |
| Health check (for monitoring) | `GET https://neostay.hospital.local/api/health` → `{"status":"ok"}` |
| Stop | `docker compose --profile https down` (accounts are kept) |
| Start again | `docker compose --profile https up -d` |

The container restarts automatically after a reboot or a crash.

### Updating NeoStay

```bash
cd neostay
git pull
docker compose --profile https up -d --build     # omit --profile https for option B
```

Accounts and the session secret live in the `neostay-instance` Docker volume, so
updates keep them, and people stay signed in.

### Backups

The only state to back up is the accounts file:

```bash
docker compose cp app:/srv/instance/access/users.json ./neostay-users-backup.json
chmod 600 ./neostay-users-backup.json
```

It holds password *hashes*, not passwords — but protect it like a password
database. To restore, copy it back with `docker compose cp` in the other
direction. The session secret regenerates if lost; people then simply sign in again.

---

## 6. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| The browser shows **Invalid host header** | The name people typed is not in `NEOSTAY_TRUSTED_HOSTS`. Add it to `.env`, then `docker compose up -d`. |
| *Your password was accepted, but this browser did not keep the sign-in* | NeoStay was opened over `http://`. Use the `https://` address (section 3). |
| *NeoStay's sign-in service is not available at this address* | The address reaches a web server that is not NeoStay — check the proxy points to `127.0.0.1:8000`. |
| A certificate warning | Option A with `NEOSTAY_TLS=internal`: trust Caddy's root certificate, or use the hospital's certificate. |
| *Too many attempts* | 5 wrong passwords for that account (or 20 from one computer) in 15 minutes. Wait, or reset the password. |
| `app` is not `healthy` | `docker compose logs app`. Production refuses to start with unsafe settings and says why. |
| *No accounts exist yet* / nobody can sign in | Create an account (section 4). |

---

## 7. A server without internet access

Build on a machine with internet access and copy the images across:

```bash
# on the connected machine, in the repository
docker compose build
docker pull caddy:2
docker save neostay:latest caddy:2 | gzip > neostay-images.tar.gz

# on the server, in a copy of the repository
gunzip -c neostay-images.tar.gz | docker load
docker compose --profile https up -d          # no --build
```

---

## 8. Security summary for IT review

* Sign-in is enforced by the server: pages load without sign-in, but hold no
  data; the data files and every API route answer `401` until a valid session
  exists. Production refuses to start without sign-in or with a weak secret.
* Passwords are stored as PBKDF2-HMAC-SHA256 hashes (600,000 iterations,
  per-account salt). Sessions are signed, expiring, `HttpOnly`, `Secure`,
  `SameSite=Lax` cookies, re-checked against the accounts file on every request.
* Failed sign-ins are rate limited per account and per client; sign-in posted
  from another website is refused; unknown addresses and wrong passwords get the
  same answer in the same time.
* Strict Content-Security-Policy, `X-Frame-Options: DENY`, HSTS, unknown host
  names refused, no-store caching for data and API.
* The container runs as a non-root user; only the accounts and the session
  secret are writable. No patient-level data exists in the application.

See [SECURITY.md](../SECURITY.md) for the full policy and its limits.
