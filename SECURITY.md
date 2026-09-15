# Security and privacy policy

NeoStay is a decision-support prototype built on **aggregated** neonatal outcome
statistics and synthetic timeline data. It is not a medical device, and it is
not a place to enter, store or process patient-level data.

## Report a vulnerability

Do not open a public issue containing exploit details, credentials, private host
names or data. Use the repository's private security-advisory workflow where
available, or contact the project leads directly. Include only what is needed to
reproduce the problem, with any real data replaced by synthetic examples.

## Who can use NeoStay

NeoStay is for registered users only. Every page first shows a sign-in screen;
the data bundles and the engine load only after sign-in. There are two
deployments, with different guarantees.

### A NeoStay server (hospital deployment)

- **The server enforces sign-in.** Pages hold no data. The data files
  (`/data/...`) and every API route except `/api/health` and the sign-in routes
  answer `401` without a valid session.
- **Accounts** live in `instance/access/users.json` (a Docker volume in
  production), written with owner-only permissions. Passwords are stored as
  PBKDF2-HMAC-SHA256 hashes with a random per-account salt and 600,000
  iterations, and must be at least 12 characters. Treat the file as a password
  database.
- **Sessions** are signed, expiring, `HttpOnly`, `SameSite=Lax` cookies, also
  `Secure` in production. Every request re-checks them against the accounts
  file, so removing an account or changing its password ends its sessions at once.
- **Guessing is slowed:** failed sign-ins are rate limited per account (5 in 15
  minutes) and per client (20); sign-in posted from another website is refused;
  an unknown email gets the same answer, in the same time, as a wrong password.
- **Production refuses to start** without sign-in (`NEOSTAY_AUTH_MODE=password`
  with a 32+ character session secret, or `proxy` with a 32+ character proxy
  secret), or with a wildcard trusted host.
- **Defence in depth:** Content-Security-Policy, `X-Frame-Options: DENY`, HSTS
  in production, trusted-host validation, no-store caching for data and API,
  API documentation off by default, and a non-root container.

Limits: the rate limit is kept in one server process; several processes need a
shared store first. HTTPS must be provided in front of the server
(`docs/DEPLOYMENT.md`).

### The GitHub Pages copy

A static site cannot check who is asking, so the build publishes one of two shapes:

- **No accounts:** the public landing page only — no application code, no data.
- **With accounts** (the `NEOSTAY_USERS_JSON` repository secret): the
  application, with its data sealed with AES-256-GCM under a fresh random key on
  every build. That key is wrapped for each account with the account's
  PBKDF2-SHA256 password hash, which the reader's browser re-derives at sign-in.
  No readable data, email address, name or password hash is published; the build
  and the workflow both refuse otherwise.

Its limits, which a server does not share:

- Anyone can download the sealed files and try passwords offline, slowed only by
  the 600,000 PBKDF2 iterations. Use long, unique passwords for these accounts.
- Removing an account protects only copies published afterwards; anyone who
  opened an earlier copy may have kept it.
- The application's code and page text are public; only the data is sealed.
- `NEOSTAY_USERS_JSON` contains password hashes: store it only as an Actions secret.

### The repository itself

**Sign-in protects the website, not this Git repository.** While the repository
is public, its source datasets (`datasets/`, `generated_data/`) and data bundles
(`frontend/data/`) — and every earlier copy in the `gh-pages` branch history —
can be read on GitHub by anyone. If the data must be restricted, make the
repository private (GitHub Pages for private repositories needs a paid GitHub
plan) or remove the data from the repository and its history.

## Data boundary

- Only aggregated statistics and synthetic data belong in this project.
- Accounts, session secrets, environment files, certificates and keys are
  excluded from Git and from Docker images (`.gitignore`, `.dockerignore`).
- What people type into the tools is computed in their browser and is not sent
  to the server.

## Before a production deployment

1. Follow `docs/DEPLOYMENT.md`: HTTPS, `NEOSTAY_TRUSTED_HOSTS`, first account.
2. Run `scripts/smoke_test.sh` against the deployed address.
3. Confirm the hospital's access-review, audit, retention and incident-response
   requirements are met.

## Use of AI-assisted development tools

AI-assisted tools were used to help write this code and documentation.
Responsibility for its architecture, security design, testing and validation
remains with the Technical Lead (see [CONTRIBUTORS.md](CONTRIBUTORS.md)).
