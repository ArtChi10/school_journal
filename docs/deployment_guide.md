# Production Deployment Guide

This guide describes manual HTTP deployment and GitHub Actions SSH deployment for the Docker Compose production stack. It does not cover HTTPS or server provisioning automation.

## Server Preparation

1. Provision a Linux server with inbound TCP port `80` open.
2. Install Docker Engine and the Docker Compose plugin.
3. Create a deploy directory, for example `/opt/school_journal`.
4. Keep production secrets outside git. Do not commit `.env.production`, credential JSON files, database dumps, or runtime logs.

## Clone Or Update The Repository

For a fresh server:

```bash
cd /opt
git clone <repository-url> school_journal
cd /opt/school_journal
```

For an existing checkout:

```bash
cd /opt/school_journal
git pull --ff-only
```

## Create `.env.production`

Copy the template and edit every placeholder:

```bash
cp .env.production.example .env.production
nano .env.production
```

Required changes:

- Set `DJANGO_SECRET_KEY` to a unique production secret.
- Set `DJANGO_ALLOWED_HOSTS` to the server IP or host.
- Set `DJANGO_CSRF_TRUSTED_ORIGINS` to `http://<SERVER_IP>` or the HTTP host.
- Replace `POSTGRES_PASSWORD` and the password inside `DATABASE_URL`.
- Fill Google, OpenAI, and Telegram values only if those features are used.

The production compose file also supports PostgreSQL settings through `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, and `POSTGRES_PORT`. `DATABASE_URL` takes precedence when present.

## Credentials Volume

The app mounts `/app/creds` as a persistent Docker volume named `creds_data`. If Google OAuth or service account access is used, place the credential files into that volume using a one-off container or another server-side copy process. Keep credential JSON files out of git.

Expected production paths:

- `/app/creds/google/client_secret.json`
- `/app/creds/google/token.json`
- `/app/creds/service_account.json`

## Start Production Stack

Run Docker Compose with the explicit env file:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

If the server already has another reverse proxy bound to port `80`, use a server-local override file instead of editing the committed production compose file:

```bash
cp docker-compose.prod.yml docker-compose.server.yml
sed -i 's/"80:80"/"8082:80"/' docker-compose.server.yml
docker compose --env-file .env.production -f docker-compose.server.yml up -d --build
```

In that case, expose or forward the external HTTP port to the chosen server port and run smoke checks against that external port.

The stack starts:

- `db`: PostgreSQL with persistent `postgres_data`
- `web`: Django app behind Gunicorn
- `proxy`: Caddy HTTP reverse proxy on port `80`

The `web` service waits for a healthy PostgreSQL service before starting.

## Check Containers And Logs

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 db
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 web
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 proxy
```

Expected state:

- `db` is healthy.
- `web` is healthy.
- `proxy` is running.
- No migration, static collection, or startup errors appear in `web` logs.

If `web` fails with `exec: "/app/docker-entrypoint.sh": permission denied`, make sure `docker-entrypoint.sh` is executable in the git checkout, then rebuild the image.

## HTTP Smoke Check

Replace `<SERVER_IP>` with the server IP or HTTP host:

```bash
curl -I http://<SERVER_IP>/
curl -I http://<SERVER_IP>/links/
curl -I http://<SERVER_IP>/runs/
curl -sS http://<SERVER_IP>/healthz
curl -sS http://<SERVER_IP>/readyz
```

Expected results:

- `/`, `/links/`, and `/runs/` return HTTP success or an expected login/redirect response.
- `/healthz` returns `{"status":"ok"}`.
- `/readyz` returns `{"status":"ok", ...}` when database and critical env checks pass.

## Stop Or Restart

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml restart web proxy
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

Do not remove Docker volumes during a normal restart. Removing `postgres_data` deletes the production database.

## GitHub Actions SSH Deploy

The `Deploy` workflow is CD only. It does not configure HTTPS, does not overwrite `.env.production`, and does not create or upload server secrets. It runs pre-deploy Django checks and tests, then deploys over SSH only when those checks pass.

Configure these GitHub repository secrets:

| Name | Purpose |
| --- | --- |
| `DEPLOY_HOST` | SSH host for the production server. |
| `DEPLOY_USER` | SSH user on the production server. |
| `DEPLOY_SSH_KEY` | Private SSH key that can access the server. |
| `DEPLOY_PORT` | Optional SSH port. Leave unset to use `22`. |

Configure these GitHub repository variables:

| Name | Current value |
| --- | --- |
| `DEPLOY_PATH` | `/opt/school_journal` |
| `DEPLOY_COMPOSE_FILE` | `docker-compose.server.yml` |
| `DEPLOY_HEALTH_URL` | `http://195.54.178.243:16472/healthz` |

The server currently uses a local `docker-compose.server.yml` with `8082:80` because another reverse proxy already owns port `80`. The external forwarded URL is `http://195.54.178.243:16472/`.

The deploy SSH user must be able to run `docker compose` on the server without an interactive password prompt. On Ubuntu this usually means adding the deploy user to the `docker` group and starting a new login session before running the workflow.

Automatic deploy runs on `push` to `main`. To run it manually, open GitHub Actions, select `Deploy`, then choose `Run workflow` on `main`.

During deploy, the workflow runs these server-side commands inside `DEPLOY_PATH`:

```bash
git fetch --all --prune
git checkout main
git pull --ff-only origin main
docker compose -f "$DEPLOY_COMPOSE_FILE" pull || true
docker compose -f "$DEPLOY_COMPOSE_FILE" up -d --build
docker compose -f "$DEPLOY_COMPOSE_FILE" ps
docker compose -f "$DEPLOY_COMPOSE_FILE" logs --tail=100 web
```

After SSH deploy, the workflow checks `DEPLOY_HEALTH_URL` with `curl -fsS`. A failed health check fails the workflow.

Rollback is currently manual: SSH to the server, check out the previous known-good commit, and run `docker compose -f docker-compose.server.yml up -d --build`. Automated rollback is a future task.
