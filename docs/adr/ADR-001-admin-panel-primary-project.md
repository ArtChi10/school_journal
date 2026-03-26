# ADR-001: Primary Django project and bounded-context app map

- Status: Accepted
- Date: 2026-03-26

## Context

Репозиторий содержит два Django-контура:

1. `admin_panel` (текущий production entrypoint с `manage.py`, `admin_panel.settings`, `admin_panel.urls`).
2. `webapp/config` (вторичный контур с отдельными `settings.py` и `urls.py`).

Это создает риск дрейфа конфигурации и неоднозначного запуска.

## Decision

1. **Primary project = `admin_panel`**.
   - Единственный активный entrypoint: `manage.py` + `admin_panel.settings` + `admin_panel.urls`.
   - `ROOT_URLCONF` остается `admin_panel.urls`.

2. **`webapp/config` не используется как отдельный project** в целевом контуре.
   - Файлы `webapp/config/*` не удаляются в этой задаче, но не считаются primary runtime.

3. **`notifications` временно исполняет роль bounded context `telegram_bot`**.
   - Физическое переименование `notifications -> telegram_bot` откладывается в отдельную задачу рефакторинга.

## Target app map and responsibility boundaries

- `journal_links` — ClassSheetLink + UI классов/таблиц.
- `jobs` — JobRun/JobLog + инфраструктура запуска и логирования.
- `validation` — проверка workbook/sheets + issues.
- `notifications` (temporary alias of `telegram_bot`) — контакты, отправки, webhook, антидубли.
- `pipeline` — шаги 021..025 + оркестрация.
- `webapp` — UI/pages/роутинг.

## Consequences

- Новые app-модули подключаются через `INSTALLED_APPS` в `admin_panel/settings.py`.
- Telegram webhook остается в `admin_panel/urls.py` и продолжает работать через `notifications.views.telegram_webhook`.
- Проверки проекта (`manage.py check`, `showmigrations`) выполняются в едином контуре `admin_panel`.