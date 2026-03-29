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