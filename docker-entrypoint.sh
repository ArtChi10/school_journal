#!/usr/bin/env sh
set -eu

cd /app

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"