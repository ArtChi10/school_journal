# Release Readiness

Use this checklist before promoting the production Docker Compose stack.

## Checklist

- [ ] Production secrets are not committed to git.
- [ ] `.env.production` exists only on the server and is not tracked.
- [ ] `DJANGO_SECRET_KEY` is unique for production.
- [ ] `DJANGO_DEBUG=False`.
- [ ] `DJANGO_ALLOWED_HOSTS` contains the server IP or HTTP host.
- [ ] `DJANGO_CSRF_TRUSTED_ORIGINS` contains the HTTP origin.
- [ ] PostgreSQL credentials in `.env.production` and `DATABASE_URL` match.
- [ ] If server port `80` is already occupied, a server-local compose override maps the proxy to the forwarded HTTP port.
- [ ] PostgreSQL `postgres_data` volume exists.
- [ ] Static files volume exists.
- [ ] Media volume exists.
- [ ] Logs volume exists.
- [ ] Credentials volume exists.
- [ ] `docker-entrypoint.sh` is executable before building the production image.
- [ ] `db` container is healthy.
- [ ] `web` container is healthy.
- [ ] `proxy` container is running.
- [ ] HTTP smoke URL `/` opens.
- [ ] HTTP smoke URL `/links/` opens.
- [ ] HTTP smoke URL `/runs/` opens.
- [ ] HTTP smoke URL `/healthz` returns `ok`.
- [ ] HTTP smoke URL `/readyz` returns `ok`.
- [ ] Runtime logs do not show migration, static collection, or startup errors.
- [ ] Future task: document and test PostgreSQL backup and restore.
- [ ] Future task: add HTTPS/TLS configuration.
- [ ] Future task: add CI/CD deployment automation.
