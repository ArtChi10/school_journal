# School Journal

## Env

Проект работает только через переменные окружения. Для локального запуска:

1. Скопируйте шаблон:
   ```bash
   cp .env.example .env
   ```
2. Заполните `.env` реальными значениями (токены, ключи, пути к Google credentials, SMTP и т.п.).
3. Не коммитьте `.env` и credential-файлы (`.gitignore` уже настроен).

### Ключевые переменные

- Django: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `TZ`
- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `ADMIN_LOG_CHAT_ID`
- OpenAI: `OPENAI_API_KEY`, `OPENAI_CRITERIA_MODEL`
- Google: `GOOGLE_ACCESS_MODE`, `GOOGLE_OAUTH_CLIENT_SECRET_PATH`, `GOOGLE_OAUTH_TOKEN_PATH`, `GOOGLE_SERVICE_ACCOUNT_JSON_PATH`, `GOOGLE_REVIEW_FOLDER_ID`, `GOOGLE_REVIEW_FOLDER_MAP`
- SMTP (legacy scripts): `SMTP_LOGIN`, `SMTP_PASSWORD`, `SMTP_FROM`
- EduPage (legacy scripts): `EDUPAGE_USERNAME`, `EDUPAGE_PASSWORD`, `EDUPAGE_SCHOOL`, `EDUPAGE_*`

См. полный перечень и дефолты в `.env.example`.

Для закрытых Google Sheets используйте `GOOGLE_ACCESS_MODE=oauth_owner`, положите OAuth client secret в `creds/google/client_secret.json`, затем на странице `Классы и таблицы` нажмите `Подключить Google`. Redirect URI должен быть добавлен в Google Cloud OAuth client; локально это обычно `http://127.0.0.1:8000/links/google/oauth/callback/`.

## Healthcheck и мониторинг ошибок

- `GET /healthz` — быстрый liveness-check, всегда отвечает `{"status":"ok"}` при работающем Django.
- `GET /readyz` — расширенный readiness-check:
  - проверка доступности БД (`SELECT 1`);
  - проверка обязательных env из `CRITICAL_ENV_VARS` (через запятую).
  - при проблемах возвращает `503` и `{"status":"degraded","checks":...}`.

### Где смотреть ошибки

- Общий лог приложения: `APP_LOG_FILE` (по умолчанию `logs/app.log`) — уровни INFO/WARNING/ERROR.
- Канал ошибок job/pipeline/telegram/validation: `APP_JOB_ERROR_LOG_FILE` (по умолчанию `logs/jobs_errors.log`) — только ERROR.
- Sentry подключается только через env:
  - `SENTRY_DSN`
  - `SENTRY_ENVIRONMENT`
  - `SENTRY_TRACES_SAMPLE_RATE`

### Как быстро проверить

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/readyz
tail -n 100 logs/app.log
tail -n 100 logs/jobs_errors.log
```


```

## Docker / deploy

1. Подготовьте env и креды:
   ```bash
   cp .env.example .env
   mkdir -p creds
   # поместите JSON-файлы Google credentials в ./creds
   ```
2. Запуск:
   ```bash
   docker compose up --build
   ```

Что происходит при старте контейнера:
- `python manage.py migrate --noinput`
- `python manage.py collectstatic --noinput`
- запуск `gunicorn admin_panel.wsgi:application`

Хранилища в compose:
- `static_data` → `/app/staticfiles`
- `media_data` → `/app/media`
- `logs_data` → `/app/logs`
- `./creds` → `/app/creds` (OAuth callback writes `token.json` here)

Быстрые проверки:
```bash
curl -sS http://127.0.0.1:8000/healthz

docker compose exec web python manage.py build_criteria_table --all-active
```
