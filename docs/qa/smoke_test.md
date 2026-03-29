# Smoke test (E2E): TASK-033

## Цель
Проверить сквозной happy-path и контроль артефактов по цепочке:

1. Добавление ссылки на класс в UI.
2. `run_validation`.
3. `send_validation_reminders`.
4. Учитель подтверждает «исправил» в Telegram.
5. Запуск полного pipeline.
6. Отправка PDF-отчётов родителям.

---

## 1) Предусловия

### 1.1 Доступы и роли
- QA-пользователь в админ-панели с правами:
  - `journal_links.view_classsheetlink`
  - `journal_links.add_classsheetlink`
  - `journal_links.change_classsheetlink`
  - `jobs.view_jobrun`
  - `jobs.run_validation`
  - `jobs.send_reminders`
  - `jobs.run_full_pipeline`
- Доступ к Telegram-боту (бот запущен, webhook настроен на `/telegram/webhook`).
- Доступ к SMTP/почте для отправки родителям.

### 1.2 Окружение
- Приложение запущено и отвечает:
  - `GET /healthz` → `{"status":"ok"}`
  - `GET /readyz` → `ok`/`degraded` без блокирующих ошибок по env.
- Заполнены ключевые env:
  - Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `ADMIN_LOG_CHAT_ID`
  - Google: `GOOGLE_ACCESS_MODE`, `GOOGLE_*` для чтения таблиц/загрузок
  - Pipeline parent reports: `PARENT_REPORTS_CONTACTS_JSON` **или** `PARENT_REPORTS_CONTACTS_CSV`
  - PDF: `PDF_CONVERT_MODE`, `PDF_OUTPUT_ROOT`

### 1.3 Тестовые данные (минимум)
Подготовить **один класс** (например `7D`) и:

1. **1 рабочий(их) лист(а)** в Google Sheet с данными для валидации.
2. **1–2 учителя** в `TeacherContact` с рабочими `chat_id` и `is_active=True`, имена должны совпадать с `teacher_name` в проблемных строках валидации.
3. **1–2 email родителя** в `PARENT_REPORTS_CONTACTS_JSON`/CSV для учащихся этого класса.

> Рекомендуется держать отдельный тестовый класс (`7D`) и тестовых пользователей/контакты, чтобы не затронуть боевые данные.

### 1.4 Файлы-артефакты до старта
- Папка логов доступна (`logs/app.log`, `logs/jobs_errors.log`).
- Папки для артефактов pipeline существуют/создаются автоматически (`output/docx`, `output/pdf` или значения из env).

---

## 2) Шаги smoke-теста (детально)

### Шаг 1. Добавить ссылку на класс в UI
1. Открыть страницу `Классы и таблицы`.
2. Нажать `Добавить ссылку`.
3. Заполнить форму:
   - `class_code`: `7D`
   - `subject_name`: тестовый предмет (например, `Math`)
   - `teacher_name`: имя, совпадающее с `TeacherContact.name`
   - `google_sheet_url`: рабочий URL таблицы
4. Сохранить.

**Ожидаемый результат**
- В таблице появился новый ряд со ссылкой.
- `is_active=True`.
- Для строки доступна кнопка `Проверить заполненность`.

**Проверяемый артефакт**
- Запись на странице списка классов + поле `updated_at` обновлено.

---

### Шаг 2. Запустить `run_validation`
Вариант A (через UI):
1. В строке класса нажать `Проверить заполненность`.
2. Откроется страница детали `JobRun`.

Вариант B (CLI):
```bash
python manage.py run_validation --class-code 7D
```

**Ожидаемый результат**
- Создан `JobRun` с `job_type=run_validation`.
- Статус завершён (`success` или `partial`; `failed` — дефект/блокер).
- В `result_json` есть `summary`, `tables`, `issues`.

**Проверяемый артефакт**
- Карточка JobRun в UI + timeline logs по валидации.
- При CLI — строка `Validation job created: id=... status=...`.

---

### Шаг 3. Выполнить `send_validation_reminders`
Вариант A (UI):
1. На странице этого `JobRun` нажать `Отправить напоминания учителям`.

Вариант B (CLI):
```bash
python manage.py send_validation_reminders --job-id <RUN_VALIDATION_JOB_ID>
```

**Ожидаемый результат**
- Для учителей с issues и валидным `chat_id` отправлены Telegram-сообщения.
- В `JobLog` появились сообщения вида `Reminder sent to ...`.
- Команда возвращает `sent > 0` (если есть проблемы), `errors = 0`.

**Проверяемый артефакт**
- Сообщение в Telegram у тестового учителя.
- Записи в timeline logs/job logs.

---

### Шаг 4. Учитель подтверждает «исправил» в Telegram
1. В Telegram из чата учителя отправить сообщение: `исправил`.
   - Допустимо: `исправила`, `готово`, `done`, `fixed`.
2. При необходимости указать job id: `исправил <JOB_ID>`.

**Ожидаемый результат**
- Webhook принимает сообщение.
- В системе создана/обновлена запись подтверждения (`TeacherConfirmation`) для нужного `JobRun`.
- В `JobLog` есть событие `Teacher confirmation received`.

**Проверяемый артефакт**
- Блок `Подтверждения учителей` на странице `JobRun` содержит запись.
- В timeline logs есть соответствующая запись с `chat_id` и `teacher`.

---

### Шаг 5. Запуск полного pipeline
Вариант A (UI):
1. Перейти в список запусков (`jobrun_list`).
2. Нажать `Run full pipeline`.

Вариант B (через shell/вызов функции):
```bash
python manage.py shell -c "from pipeline.full_pipeline_runner import run_full_pipeline; j=run_full_pipeline(); print(j.id, j.status)"
```

**Ожидаемый результат**
- Создан `JobRun` с `job_type=run_full_pipeline`.
- В `result_json.pipeline_steps` зафиксированы шаги TASK-021..TASK-025.
- По каждому шагу есть статус + summary + лог `step_started/step_success/step_failed`.

**Проверяемый артефакт**
- Раздел `Pipeline steps` в UI с деталями статусов.
- Разделы `Artifacts` и `Errors` в деталях запуска.

---

### Шаг 6. Отправка PDF отчётов родителям
> Обычно это шаг TASK-025 в полном pipeline. Дополнительно можно прогнать отдельной командой `send_parent_reports`.

1. Проверить, что PDFs созданы на шаге TASK-024 (в `PDF_OUTPUT_ROOT`/`output/pdf`).
2. Убедиться, что на шаге TASK-025 есть контакты родителей.
3. При необходимости повторить отдельно:
```bash
python manage.py send_parent_reports --contacts-json <path/to/contacts.json> --pdf-root <path/to/pdf_root>
```

**Ожидаемый результат**
- Для валидных пар `ученик -> email` статус отправки успешный.
- В `result_json` job-а: `sent_success > 0`, контролируемые значения `sent_failed`, `skipped_no_contact`, `skipped_no_pdf`.
- На диске присутствуют PDF-файлы отчётов.

**Проверяемый артефакт**
- `JobRun` (тип `send_parent_reports` или TASK-025 внутри full pipeline) с итоговой статистикой.
- Физические PDF-файлы в output-папке.
- Почтовый артефакт (входящее письмо в тестовом ящике родителя).

---

## 3) Таблица проверки (заполняет QA)

| step | expected | actual | pass/fail | комментарий |
|---|---|---|---|---|
| 1. Добавление ссылки в UI | Ссылка создана, активна, видна кнопка проверки |  |  |  |
| 2. run_validation | Создан JobRun, есть summary/tables/issues, статус не failed |  |  |  |
| 3. send_validation_reminders | Учителю ушло сообщение, в логах `Reminder sent` |  |  |  |
| 4. Подтверждение в Telegram | В `TeacherConfirmation` и логах есть `Teacher confirmation received` |  |  |  |
| 5. Полный pipeline | TASK-021..025 отражены в pipeline_steps, есть артефакты |  |  |  |
| 6. Отправка PDF родителям | PDF существуют, отправка зафиксирована, есть e-mail артефакт |  |  |  |

---

## 4) Критерии приёмки (DoD)

Сценарий считается пройденным, если:

1. QA выполняет весь сценарий **без участия разработчика**.
2. На каждом этапе есть **проверяемый артефакт** (лог, статус, файл, Telegram/e-mail сообщение).
3. Любое падение зафиксировано в таблице проверки с:
   - шагом,
   - симптомом,
   - текстом ошибки,
   - вероятной причиной,
   - ссылкой на артефакт (job id, лог, файл).

---

## 5) Шаблон фиксации падений

Использовать для каждого сбоя:

- **Шаг:**
- **Когда:**
- **Job ID / ссылка на запуск:**
- **Симптом:**
- **Ошибка (текст):**
- **Где зафиксировано:** (UI timeline / `logs/app.log` / `logs/jobs_errors.log` / Telegram / email)
- **Предполагаемая причина:**
- **Блокирует ли дальнейший smoke:** (да/нет)
- **Комментарий QA:**