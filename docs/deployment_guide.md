# Production Deployment Guide

This guide describes a manual HTTP-only deployment for the Docker Compose production stack. It does not cover HTTPS, CI/CD, or server provisioning automation.

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
