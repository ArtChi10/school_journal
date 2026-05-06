from __future__ import annotations

from typing import Any

from django.utils import timezone

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from pipeline.models import AICriteriaReportTarget
from validation.descriptor_criteria_report import (
    COLOR_GREEN,
    COLOR_HEADER,
    COLOR_RED,
    COLOR_YELLOW,
    _background_color_request,
    _build_sheets_service,
    _ensure_sheets,
    _format_tbilisi_datetime,
    _header_format_requests,
    _hyperlink_request,
    _quote_sheet_name,
    extract_spreadsheet_id,
)

SUMMARY_SHEET = "Summary"
PROBLEMS_SHEET = "Problems"
ALL_CRITERIA_SHEET = "All criteria"

AI_REPORT_COLUMNS = [
    ("class_code", "Класс"),
    ("subject_name", "Предмет"),
    ("teacher_name", "Учитель"),
    ("module_number", "Модуль"),
    ("criterion_text", "Критерий преподавателя"),
    ("ai_verdict", "Оценка AI"),
    ("ai_reason", "Причина"),
    ("ai_suggested_rewrite", "Предложение по изменению"),
    ("sheet_url", "Ссылка на таблицу"),
]
AI_REPORT_HEADERS = [label for _key, label in AI_REPORT_COLUMNS]


class AICriteriaReportError(RuntimeError):
    """Raised when AI criteria Google report export fails."""


def _safe_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _ai_verdict_label(value: Any) -> str:
    return {
        "ok": "OK",
        "problem": "Есть проблемы",
        "failed": "Ошибка AI",
    }.get(str(value or "").strip().lower(), str(value or "").strip())


def _job_status_label(value: Any) -> str:
    return {
        "pending": "Ожидает",
        "running": "Выполняется",
        "success": "Успешно",
        "failed": "Ошибка",
        "partial": "Частично",
    }.get(str(value or "").strip().lower(), str(value or "").strip())


def _report_value(row: dict[str, Any], key: str) -> Any:
    value = row.get(key)
    if key == "ai_verdict":
        return _ai_verdict_label(value)
    if key == "sheet_url":
        return "Открыть" if str(value or "").strip() else ""
    return _safe_value(value)


def _rows_from_dicts(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [AI_REPORT_HEADERS] + [[_report_value(row, key) for key, _label in AI_REPORT_COLUMNS] for row in rows]


def _hyperlink_specs_from_dicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    column_index = [key for key, _label in AI_REPORT_COLUMNS].index("sheet_url")
    specs = []
    for row_index, row in enumerate(rows, start=1):
        url = str(row.get("sheet_url") or "").strip()
        if url:
            specs.append({"row_index": row_index, "column_index": column_index, "url": url})
    return specs


def _report_payload_item(title: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "title": title,
        "values": _rows_from_dicts(rows),
        "hyperlinks": _hyperlink_specs_from_dicts(rows),
    }


def _summary_values(job_run: JobRun, *, report_status: str = "", report_updated_at: str = "") -> list[list[Any]]:
    result = job_run.result_json if isinstance(job_run.result_json, dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    rows = [
        ("ID запуска", str(job_run.id)),
        ("Начало", job_run.started_at.isoformat() if job_run.started_at else ""),
        ("Завершение", job_run.finished_at.isoformat() if job_run.finished_at else ""),
        ("Статус запуска", _job_status_label(job_run.status)),
        ("Классов проверено", summary.get("classes_checked", 0)),
        ("Критериев отправлено в AI", summary.get("criteria_sent_to_ai", 0)),
        ("Пропущено пустых", summary.get("criteria_skipped_empty", 0)),
        ("Пропущено числовых", summary.get("criteria_skipped_numeric", 0)),
        ("OK", summary.get("criteria_ok", 0)),
        ("Есть проблемы", summary.get("criteria_problem", 0)),
        ("AI-запросов всего", summary.get("ai_requests_total", 0)),
        ("AI-запросов с ошибкой", summary.get("ai_requests_failed", 0)),
        ("Статус Google-отчета", report_status or report.get("status", "")),
        ("Google-отчет обновлен", report_updated_at or report.get("updated_at_display", "") or report.get("updated_at", "")),
    ]
    return [["Показатель", "Значение"], *[[key, _safe_value(value)] for key, value in rows]]


def _sheet_title(raw_title: str, used_titles: set[str]) -> str:
    import re

    title = (raw_title or "Class").strip() or "Class"
    title = re.sub(r"[\[\]\*\?/\\:]", "-", title)[:100].strip() or "Class"
    base = title
    index = 2
    while title in used_titles:
        suffix = f" {index}"
        title = f"{base[: 100 - len(suffix)]}{suffix}"
        index += 1
    used_titles.add(title)
    return title


def build_ai_criteria_report_payload(
    job_run: JobRun,
    *,
    report_status: str = "",
    report_updated_at: str = "",
) -> list[dict[str, Any]]:
    result = job_run.result_json if isinstance(job_run.result_json, dict) else {}
    rows = [row for row in result.get("rows", []) if isinstance(row, dict)]
    problems = [row for row in rows if row.get("ai_verdict") != "ok"]
    payload = [
        {"title": SUMMARY_SHEET, "values": _summary_values(job_run, report_status=report_status, report_updated_at=report_updated_at)},
        _report_payload_item(PROBLEMS_SHEET, problems),
        _report_payload_item(ALL_CRITERIA_SHEET, rows),
    ]

    used_titles = {SUMMARY_SHEET, PROBLEMS_SHEET, ALL_CRITERIA_SHEET}
    for class_code in sorted({str(row.get("class_code") or "").strip() for row in rows if row.get("class_code")}):
        class_rows = [row for row in rows if str(row.get("class_code") or "").strip() == class_code]
        payload.append(_report_payload_item(_sheet_title(class_code, used_titles), class_rows))
    return payload


def _status_color(header: str, value: Any) -> dict[str, float] | None:
    normalized = str(value or "").strip().lower()
    if header == "Оценка AI":
        return {
            "ok": COLOR_GREEN,
            "есть проблемы": COLOR_RED,
            "ошибка ai": COLOR_YELLOW,
        }.get(normalized)
    return None


def _format_requests_for_values(
    sheet_id: int,
    values: list[list[Any]],
    hyperlinks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not values:
        return []
    headers = [str(header) for header in values[0]]
    requests = _header_format_requests(sheet_id, len(headers))
    if values and values[0] == ["Показатель", "Значение"]:
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": 2,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": COLOR_HEADER,
                            "textFormat": {"bold": True},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            }
        )
    for row_index, row_values in enumerate(values[1:], start=1):
        for column_index, header in enumerate(headers):
            value = row_values[column_index] if column_index < len(row_values) else ""
            color = _status_color(header, value)
            if color:
                requests.append(_background_color_request(sheet_id, row_index, column_index, color))
    for link in hyperlinks or []:
        requests.append(_hyperlink_request(sheet_id, int(link["row_index"]), int(link["column_index"]), str(link["url"])))
    return requests


def _apply_report_formatting(service, spreadsheet_id: str, payload: list[dict[str, Any]], title_to_id: dict[str, int]) -> None:
    requests: list[dict[str, Any]] = []
    for item in payload:
        sheet_id = title_to_id.get(item["title"])
        if sheet_id is None:
            continue
        requests.extend(_format_requests_for_values(sheet_id, item["values"], item.get("hyperlinks", [])))
    if requests:
        service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()


def _write_payload(service, spreadsheet_id: str, payload: list[dict[str, Any]]) -> None:
    titles = [item["title"] for item in payload]
    title_to_id = _ensure_sheets(service, spreadsheet_id, titles)
    ranges_to_clear = []
    data_to_update = []
    for item in payload:
        quoted_title = _quote_sheet_name(item["title"])
        ranges_to_clear.append(f"{quoted_title}!A:Z")
        data_to_update.append({"range": f"{quoted_title}!A1", "values": item["values"]})

    if ranges_to_clear:
        service.spreadsheets().values().batchClear(spreadsheetId=spreadsheet_id, body={"ranges": ranges_to_clear}).execute()
    if data_to_update:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": data_to_update},
        ).execute()
    _apply_report_formatting(service, spreadsheet_id, payload, title_to_id)


def update_ai_criteria_google_report(job_run: JobRun) -> dict[str, Any]:
    target = AICriteriaReportTarget.objects.filter(is_active=True).order_by("-updated_at", "-id").first()
    if target is None:
        report = {"status": "not_configured"}
        log_step(job_run=job_run, level=JobLog.Level.INFO, message="Google AI report update skipped", context=report)
        return report

    if job_run.status not in {JobRun.Status.SUCCESS, JobRun.Status.PARTIAL}:
        report = {"status": "skipped", "target_id": target.id, "reason": f"job_status_{job_run.status}"}
        log_step(job_run=job_run, level=JobLog.Level.INFO, message="Google AI report update skipped", context=report)
        return report

    try:
        updated_at = timezone.now()
        updated_at_display = _format_tbilisi_datetime(updated_at)
        payload = build_ai_criteria_report_payload(job_run, report_status="updated", report_updated_at=updated_at_display)
        log_step(
            job_run=job_run,
            level=JobLog.Level.INFO,
            message="Google AI report update started",
            context={"target_id": target.id, "sheets_count": len(payload)},
        )
        spreadsheet_id = extract_spreadsheet_id(target.google_sheet_url)
        service = _build_sheets_service()
        _write_payload(service, spreadsheet_id, payload)
        report = {
            "status": "updated",
            "target_id": target.id,
            "updated_at": updated_at.isoformat(),
            "updated_at_display": updated_at_display,
            "sheets": [item["title"] for item in payload],
        }
        log_step(job_run=job_run, level=JobLog.Level.INFO, message="Google AI report update finished", context=report)
        return report
    except Exception as exc:  # noqa: BLE001
        report = {"status": "failed", "target_id": target.id, "error": str(exc)}
        log_step(job_run=job_run, level=JobLog.Level.ERROR, message="Google AI report update failed", context=report)
        return report
