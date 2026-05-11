#!/usr/bin/env sh
set -eu

cd /app

if [ "${DJANGO_RUN_STARTUP_TASKS:-1}" = "1" ]; then
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
fi

exec "$@"
