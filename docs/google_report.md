# Descriptor Criteria Google Report

The descriptor/criteria fill check can update one existing Google Spreadsheet after each run. The application does not create a new report file per run.

## Prepare The Report Spreadsheet

1. Create a Google Spreadsheet manually.
2. Share it with the Google account used by the app OAuth token, with edit access.
3. In the admin panel open `Классы и таблицы` -> `Google-отчет`.
4. Paste the spreadsheet URL and keep the target active.

The same spreadsheet is reused after every descriptor/criteria check.

## Updated Sheets

The report updater rewrites these sheets:

- `Summary`
- `Problems`
- `All subjects`
- one sheet per class, named by `class_code`

The `Problems` sheet contains only subject rows where `overall_status != ok`. The `All subjects` and class sheets contain every checked subject row.

Each subject row includes grade completeness fields. Grades are checked only for filled criteria columns. A criteria cell is not considered filled when it is empty or contains only a number such as `1`, `2`, or `3`. For every student row found below the `Имя` header, the checker expects a non-empty cell at the student x filled-criterion intersection. The main human-readable field is `grades_ratio`, for example `4/6`.

## OAuth Scope

Report export needs write access to Google Sheets. The OAuth token must include:

- `https://www.googleapis.com/auth/drive`
- `https://www.googleapis.com/auth/spreadsheets`

If report update fails with insufficient scopes, recreate `creds/google/token.json` locally through `Подключить Google`, then copy the new token to the production credentials volume. Do not commit `token.json` or `client_secret.json`.

## Runtime Behavior

After a descriptor/criteria check finishes:

- if no active report target exists, the run is kept successful and `report.status` becomes `not_configured`;
- if the check failed, report export is skipped;
- if report export succeeds, `report.status` becomes `updated`;
- if report export fails after a successful check, the check result is preserved and the `JobRun` is marked `partial`.

Report update events are written to `JobLog`.
