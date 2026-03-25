FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY school_journal-main/requirements.txt /tmp/legacy-requirements.txt
COPY webapp/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/legacy-requirements.txt -r /tmp/requirements.txt

COPY . /app

WORKDIR /app/webapp
RUN python manage.py migrate --noinput

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "180"]