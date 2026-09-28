# Deploying NeoStay to a cloud platform

*For hospital IT and platform engineers. NeoStay is one Linux container with no
database and no cloud-specific services, so it runs the same way on AWS, Azure,
Google Cloud, a private Kubernetes cluster, or a single virtual machine.*

> NeoStay is a decision-support prototype, not a medical device. It holds
> aggregated statistics only — no patient-level data.

---

## 1. What the platform has to provide

| Requirement | Detail |
|---|---|
| **Run a Linux container** | `linux/amd64` or `linux/arm64`. No privileged mode, no host mounts. |
| **HTTPS in front** | Browsers refuse NeoStay's sign-in cookie over plain `http://`. Every managed platform below terminates TLS for you. |
| **One environment secret** | The accounts file, and a session secret of 32+ characters. |
| **512 MB of memory, 0.25 vCPU** | Enough for a NICU-sized unit. Requests are small and stateless. |
| **Nothing else** | No database, no object storage, no queue, no managed identity, no egress to the internet at run time. |

NeoStay listens on the port in the `PORT` environment variable (default 8000),
answers health checks at `/api/health`, and reads `X-Forwarded-*` headers from
the platform's load balancer.

### Two ways to hold the accounts

| Mode | How accounts are stored | Use it when |
|---|---|---|
| **Stateless** (recommended for cloud) | `NEOSTAY_USERS_JSON` holds the accounts file; `NEOSTAY_SESSION_SECRET` signs cookies. No disk at all. Accounts change by updating the secret and redeploying. | Serverless container hosts, or any platform where you would rather not manage a volume. Scales to several replicas. |
| **Stateful** | A writable volume at `/srv/instance`. Accounts are added with a command against the running container, and take effect immediately. | A hospital server or VM, where administrators expect to add people without a deploy (see [DEPLOYMENT.md](DEPLOYMENT.md)). |

---

## 2. The image

Every push to `main` publishes a multi-architecture image:

```
ghcr.io/<owner>/neostay:latest        newest build of main
ghcr.io/<owner>/neostay:sha-<commit>  one exact commit  ← pin this in production
ghcr.io/<owner>/neostay:v1.2.3        a tagged release
```

Build it yourself instead, if the hospital requires it:

```bash
docker build -t neostay:local .
```

**Mirroring into a private registry** (most hospitals do this, and AWS App Runner
and Google Cloud Run require an image in their own registry):

```bash
# any registry: Artifact Registry, ECR, ACR, Harbor, Nexus…
docker buildx imagetools create \
  --tag <registry>/neostay:2026-09-28 \
  ghcr.io/<owner>/neostay:sha-<commit>
```

---

## 3. Prepare the two secrets

Do this once, on the machine that holds the accounts:

```bash
make user-add EMAIL=first.admin@hospital.org NAME="First Admin"   # hidden password prompt
make -s user-export > users.json                                  # the accounts file
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'     # the session secret
```

`users.json` holds PBKDF2 password hashes. Put it in the platform's secret store
(Secret Manager, Secrets Manager, Key Vault, a Kubernetes Secret) — never in an
image, a repository, or a plain environment variable in a web console that logs
its values. Delete the local copy afterwards.

---

## 4. Platform recipes

Every recipe sets the same five variables. Replace the host name with the one
your platform issues, or your own DNS name.

```
NEOSTAY_ENV=production
NEOSTAY_TRUSTED_HOSTS=<the host name people type>
NEOSTAY_USERS_JSON=<contents of users.json>
NEOSTAY_SESSION_SECRET=<32+ random characters>
FORWARDED_ALLOW_IPS=*        # the platform's load balancer is in front
```

### Google Cloud Run

```bash
gcloud secrets create neostay-users --data-file=users.json
printf '%s' "$SESSION_SECRET" | gcloud secrets create neostay-session --data-file=-

gcloud run deploy neostay \
  --image=<region>-docker.pkg.dev/<project>/<repo>/neostay:sha-<commit> \
  --region=<region> --allow-unauthenticated --port=8000 --cpu=1 --memory=512Mi \
  --set-env-vars=NEOSTAY_ENV=production,FORWARDED_ALLOW_IPS=*,NEOSTAY_TRUSTED_HOSTS=<service>.run.app \
  --set-secrets=NEOSTAY_USERS_JSON=neostay-users:latest,NEOSTAY_SESSION_SECRET=neostay-session:latest
```

`--allow-unauthenticated` lets the browser reach the sign-in page; NeoStay itself
still requires an account. Cloud Run sets `PORT`, terminates TLS, and scales to
zero. Add `--min-instances=1` to avoid a cold start on the ward.

### AWS App Runner

Push the image to ECR, store both secrets in Secrets Manager, then create the
service (console or `apprunner create-service`) with:

* **Port** 8000, **health check path** `/api/health`
* Environment variables as above, with `NEOSTAY_USERS_JSON` and
  `NEOSTAY_SESSION_SECRET` sourced from Secrets Manager
* `NEOSTAY_TRUSTED_HOSTS` set to the App Runner domain, or your custom domain

App Runner provides HTTPS and a certificate for custom domains.

### Azure Container Apps

```bash
az containerapp create -n neostay -g <resource-group> --environment <env> \
  --image ghcr.io/<owner>/neostay:sha-<commit> \
  --target-port 8000 --ingress external --min-replicas 1 --cpu 0.5 --memory 1Gi \
  --secrets users="$(cat users.json)" session="$SESSION_SECRET" \
  --env-vars NEOSTAY_ENV=production FORWARDED_ALLOW_IPS='*' \
             NEOSTAY_TRUSTED_HOSTS=<app>.<region>.azurecontainerapps.io \
             NEOSTAY_USERS_JSON=secretref:users NEOSTAY_SESSION_SECRET=secretref:session
```

### Kubernetes — EKS, AKS, GKE, OpenShift, k3s, on-premises

```bash
kubectl create secret generic neostay \
  --from-file=users.json=users.json \
  --from-literal=session-secret="$SESSION_SECRET"

# edit the image, host name and ingress class first
kubectl apply -k deploy/kubernetes
```

The manifests in [`deploy/kubernetes/`](../deploy/kubernetes/) are plain
Kubernetes: a Deployment (2 replicas, non-root, read-only root filesystem, health
probes), a ClusterIP Service, and an Ingress. Nothing in them is provider-specific
apart from the `ingressClassName` and the TLS secret you point them at.

### A single virtual machine (any provider)

Use the Docker Compose setup, which also gives you HTTPS and writable accounts:
[DEPLOYMENT.md](DEPLOYMENT.md). This is the closest equivalent to an on-premises
hospital server.

---

## 5. After deploying — check it

```bash
NEOSTAY_SMOKE_PASSWORD='the password' scripts/smoke_test.sh https://<your-host> first.admin@hospital.org
```

Every line must read `ok`: pages load without sign-in, data and API refuse a
signed-out request, sign-in works, and signing out locks them again.

---

## 6. Operating it

| Task | Stateless mode | Stateful mode |
|---|---|---|
| Add or remove a person | Update the accounts secret, then redeploy or restart the revision | `docker compose exec app python -m app.accounts add …`, effective at once |
| Rotate the session secret | Replace the secret; everyone signs in again | Delete the secret file in the volume and restart |
| Upgrade | Deploy a new image tag | `git pull && docker compose up -d --build` |
| Roll back | Deploy the previous `sha-` tag | Check out the previous commit and rebuild |

**Replicas.** Sessions are signed tokens, so any replica accepts any session and
no sticky sessions are needed — provided every replica shares
`NEOSTAY_SESSION_SECRET`. One caveat: the limit on failed sign-ins is counted
inside each process, so N replicas allow N times as many attempts before the
limit bites. For a unit-sized deployment this is not material; for a large public
deployment, move that counter to a shared store first.

**Logs and monitoring.** NeoStay logs to standard output, which every platform
collects. Point uptime checks at `/api/health`; it needs no session and returns
`{"status":"ok"}`.

---

## 7. Keeping it portable

The properties that make NeoStay easy to move between providers are worth
preserving in any future change:

* one container, configured only by environment variables;
* no managed database, queue, cache or object store;
* no cloud SDK in the image, and no calls to a metadata service;
* state limited to one optional directory, which the stateless mode removes;
* health, port and proxy behaviour driven by standard variables (`PORT`,
  `FORWARDED_ALLOW_IPS`);
* the image is built once and mirrored, never rebuilt per provider.

A move between providers is then a registry copy, five environment variables, and
a DNS change.
