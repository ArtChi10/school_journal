FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY school_journal-main/requirements.txt /tmp/legacy-requirements.txt
COPY requirements.txt /tmp/admin-requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/legacy-requirements.txt -r /tmp/admin-requirements.txt \
        Django==5.1.8 gunicorn==23.0.0 whitenoise==6.8.2

RUN addgroup --system app && adduser --system --ingroup app app


COPY . /app

RUN mkdir -p /app/staticfiles /app/media /app/logs /app/creds \
    && chown -R app:app /app

USER app
EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "admin_panel.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "180"]
