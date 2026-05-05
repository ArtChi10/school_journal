from __future__ import annotations

import os
import re
from typing import Any

from django.utils import timezone

from admin_panel.google_oauth import (
    GOOGLE_DRIVE_SCOPE,
    GOOGLE_SHEETS_SCOPE,
    get_google_oauth_client_secret_path,
    get_google_oauth_token_path,
)
from jobs.models import JobLog, JobRun
from jobs.services import log_step
from journal_links.models import DescriptorCriteriaReportTarget

GOOGLE_REPORT_SCOPES = [GOOGLE_DRIVE_SCOPE, GOOGLE_SHEETS_SCOPE]
_GOOGLE_SHEET_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")

SUMMARY_SHEET = "Summary"
PROBLEMS_SHEET = "Problems"
ALL_SUBJECTS_SHEET = "All subjects"

COLOR_GREEN = {"red": 0.85, "green": 0.94, "blue": 0.85}
COLOR_YELLOW = {"red": 1.0, "green": 0.95, "blue": 0.8}
COLOR_RED = {"red": 0.98, "green": 0.8, "blue": 0.8}
COLOR_GRAY = {"red": 0.9, "green": 0.9, "blue": 0.9}
COLOR_HEADER = {"red": 0.93, "green": 0.94, "blue": 0.96}

ALL_SUBJECTS_HEADERS = [
    "class_code",
    "subject_name",
    "teacher_name",
    "module_number",
    "descriptor_status",
    "criteria_status",
    "criteria_filled",
    "criteria_total",
    "criteria_missing",
    "grades_ratio",
    "grades_status",
    "grades_filled",
    "grades_total",
    "grades_missing",
    "overall_status",
    "sheet_url",
]
PROBLEMS_HEADERS = [
    "class_code",
    "subject_name",
    "teacher_name",
    "module_number",
    "descriptor_status",
    "criteria_status",
    "criteria_filled",
    "criteria_total",
    "criteria_missing",
    "grades_ratio",
    "grades_status",
    "grades_filled",
    "grades_total",
    "grades_missing",
    "overall_status",
    "sheet_url",
]


class DescriptorCriteriaReportError(RuntimeError):
    """Raised when descriptor/criteria Google report export fails."""


def extract_spreadsheet_id(url: str) -> str:
    match = _GOOGLE_SHEET_RE.search(url or "")
    if not match:
        raise DescriptorCriteriaReportError("Could not extract Google Spreadsheet id from report URL")
    return match.group(1)


def _safe_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _rows_from_dicts(rows: list[dict], headers: list[str]) -> list[list[Any]]:
    return [headers] + [[_safe_value(row.get(header)) for header in headers] for row in rows]


def _summary_values(job_run: JobRun, *, report_status: str = "", report_updated_at: str = "") -> list[list[Any]]:
    result = job_run.result_json if isinstance(job_run.result_json, dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    rows = [
        ("run_id", str(job_run.id)),
        ("started_at", job_run.started_at.isoformat() if job_run.started_at else ""),
        ("finished_at", job_run.finished_at.isoformat() if job_run.finished_at else ""),
        ("status", job_run.status),
        ("classes_checked", summary.get("classes_checked", 0)),
        ("subjects_checked", summary.get("subjects_checked", 0)),
        ("fully_filled", summary.get("fully_filled", 0)),
        ("with_problems", summary.get("with_problems", 0)),
        ("tables_total", summary.get("tables_total", 0)),
        ("tables_success", summary.get("tables_success", 0)),
        ("tables_failed", summary.get("tables_failed", 0)),
        ("sheets_total", summary.get("sheets_total", 0)),
        ("sheets_checked", summary.get("sheets_checked", 0)),
        ("sheets_skipped", summary.get("sheets_skipped", 0)),
        ("report_status", report_status or report.get("status", "")),
        ("report_updated_at", report_updated_at or report.get("updated_at", "")),
    ]
    return [["metric", "value"], *[[key, _safe_value(value)] for key, value in rows]]


def _sheet_title(raw_title: str, used_titles: set[str]) -> str:
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


def build_descriptor_criteria_report_payload(
    job_run: JobRun,
    *,
    report_status: str = "",
    report_updated_at: str = "",
) -> list[dict[str, Any]]:
    result = job_run.result_json if isinstance(job_run.result_json, dict) else {}
    rows = [row for row in result.get("rows", []) if isinstance(row, dict)]
    problems = [row for row in rows if row.get("overall_status") != "ok"]

    payload = [
        {
            "title": SUMMARY_SHEET,
            "values": _summary_values(
                job_run,
                report_status=report_status,
                report_updated_at=report_updated_at,
            ),
        },
        {"title": PROBLEMS_SHEET, "values": _rows_from_dicts(problems, PROBLEMS_HEADERS)},
        {"title": ALL_SUBJECTS_SHEET, "values": _rows_from_dicts(rows, ALL_SUBJECTS_HEADERS)},
    ]

    used_titles = {SUMMARY_SHEET, PROBLEMS_SHEET, ALL_SUBJECTS_SHEET}
    for class_code in sorted({str(row.get("class_code") or "").strip() for row in rows if row.get("class_code")}):
        class_rows = [row for row in rows if str(row.get("class_code") or "").strip() == class_code]
        payload.append({"title": _sheet_title(class_code, used_titles), "values": _rows_from_dicts(class_rows, ALL_SUBJECTS_HEADERS)})

    return payload


def _require_env_path(var_name: str):
    from pathlib import Path

    raw = (os.getenv(var_name) or "").strip()
    if not raw:
        raise DescriptorCriteriaReportError(f"{var_name} is required")
    path = Path(raw)
    if not path.exists():
        raise DescriptorCriteriaReportError(f"{var_name} file does not exist: {path}")
    return path


def _build_sheets_service():
    mode = (os.getenv("GOOGLE_ACCESS_MODE") or "oauth_owner").strip().lower()
    if mode not in {"oauth_owner", "service_account"}:
        raise DescriptorCriteriaReportError("Report export supports only GOOGLE_ACCESS_MODE=oauth_owner or service_account")

    from googleapiclient.discovery import build

    if mode == "oauth_owner":
        token_path = get_google_oauth_token_path()
        client_secret_path = get_google_oauth_client_secret_path()
        if not token_path.exists():
            raise DescriptorCriteriaReportError(f"GOOGLE_OAUTH_TOKEN_PATH file does not exist: {token_path}")
        if not client_secret_path.exists():
            raise DescriptorCriteriaReportError(f"GOOGLE_OAUTH_CLIENT_SECRET_PATH file does not exist: {client_secret_path}")

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(token_path))
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise DescriptorCriteriaReportError("OAuth token is invalid and cannot be refreshed")
    else:
        creds_path = _require_env_path("GOOGLE_SERVICE_ACCOUNT_JSON_PATH")
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(str(creds_path), scopes=GOOGLE_REPORT_SCOPES)

    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _quote_sheet_name(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _sheet_metadata(service, spreadsheet_id: str) -> dict[str, int]:
    metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))").execute()
    return {sheet["properties"]["title"]: sheet["properties"].get("sheetId") for sheet in metadata.get("sheets", [])}


def _ensure_sheets(service, spreadsheet_id: str, titles: list[str]) -> dict[str, int]:
    title_to_id = _sheet_metadata(service, spreadsheet_id)
    existing_titles = set(title_to_id)
    requests = [{"addSheet": {"properties": {"title": title}}} for title in titles if title not in existing_titles]
    if requests:
        service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
        title_to_id = _sheet_metadata(service, spreadsheet_id)
    return title_to_id


def _background_color_request(sheet_id: int, row_index: int, column_index: int, color: dict[str, float]) -> dict[str, Any]:
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row_index,
                "endRowIndex": row_index + 1,
                "startColumnIndex": column_index,
                "endColumnIndex": column_index + 1,
            },
            "cell": {"userEnteredFormat": {"backgroundColor": color}},
            "fields": "userEnteredFormat.backgroundColor",
        }
    }


def _header_format_requests(sheet_id: int, column_count: int) -> list[dict[str, Any]]:
    return [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1000,
                    "startColumnIndex": 0,
                    "endColumnIndex": max(column_count, 1),
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                        "textFormat": {"bold": False},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": max(column_count, 1),
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": COLOR_HEADER,
                        "textFormat": {"bold": True},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": max(column_count, 1),
                }
            }
        },
    ]


def _status_color(header: str, value: Any, row: dict[str, Any]) -> dict[str, float] | None:
    normalized_value = str(value or "").strip().lower()
    if header == "descriptor_status":
        return {"filled": COLOR_GREEN, "missing": COLOR_YELLOW, "not_found": COLOR_RED}.get(normalized_value)
    if header == "criteria_status":
        return {"filled": COLOR_GREEN, "missing": COLOR_YELLOW, "not_found": COLOR_RED}.get(normalized_value)
    if header == "grades_status":
        return {"ok": COLOR_GREEN, "missing": COLOR_YELLOW, "not_applicable": COLOR_GRAY}.get(normalized_value)
    if header == "overall_status":
        return {"ok": COLOR_GREEN, "problem": COLOR_RED}.get(normalized_value)
    if header in {"criteria_missing", "grades_missing"}:
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            return None
        return COLOR_GREEN if count == 0 else COLOR_YELLOW
    if header == "grades_ratio":
        return _status_color("grades_status", row.get("grades_status"), row)
    return None


def _format_requests_for_values(sheet_id: int, values: list[list[Any]]) -> list[dict[str, Any]]:
    if not values:
        return []

    headers = [str(header) for header in values[0]]
    requests = _header_format_requests(sheet_id, len(headers))
    headers_to_format = {
        "descriptor_status",
        "criteria_status",
        "criteria_missing",
        "grades_ratio",
        "grades_status",
        "grades_missing",
        "overall_status",
    }
    for row_index, row_values in enumerate(values[1:], start=1):
        row = {header: row_values[index] if index < len(row_values) else "" for index, header in enumerate(headers)}
        for column_index, header in enumerate(headers):
            if header not in headers_to_format:
                continue
            value = row_values[column_index] if column_index < len(row_values) else ""
            color = _status_color(header, value, row)
            if color:
                requests.append(_background_color_request(sheet_id, row_index, column_index, color))
    return requests


def _apply_report_formatting(service, spreadsheet_id: str, payload: list[dict[str, Any]], title_to_id: dict[str, int]) -> None:
    requests: list[dict[str, Any]] = []
    for item in payload:
        sheet_id = title_to_id.get(item["title"])
        if sheet_id is None:
            continue
        requests.extend(_format_requests_for_values(sheet_id, item["values"]))
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
        service.spreadsheets().values().batchClear(
            spreadsheetId=spreadsheet_id,
            body={"ranges": ranges_to_clear},
        ).execute()
    if data_to_update:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": data_to_update},
        ).execute()
    _apply_report_formatting(service, spreadsheet_id, payload, title_to_id)


def update_descriptor_criteria_google_report(job_run: JobRun) -> dict[str, Any]:
    target = DescriptorCriteriaReportTarget.objects.filter(is_active=True).order_by("-updated_at", "-id").first()
    if target is None:
        report = {"status": "not_configured"}
        log_step(job_run=job_run, level=JobLog.Level.INFO, message="Report update skipped", context=report)
        return report

    if job_run.status not in {JobRun.Status.SUCCESS, JobRun.Status.PARTIAL}:
        report = {"status": "skipped", "target_id": target.id, "reason": f"job_status_{job_run.status}"}
        log_step(job_run=job_run, level=JobLog.Level.INFO, message="Report update skipped", context=report)
        return report

    try:
        updated_at = timezone.now().isoformat()
        payload = build_descriptor_criteria_report_payload(
            job_run,
            report_status="updated",
            report_updated_at=updated_at,
        )
        log_step(
            job_run=job_run,
            level=JobLog.Level.INFO,
            message="Report update started",
            context={"target_id": target.id, "sheets_count": len(payload)},
        )
        spreadsheet_id = extract_spreadsheet_id(target.google_sheet_url)
        service = _build_sheets_service()
        _write_payload(service, spreadsheet_id, payload)
        report = {
            "status": "updated",
            "target_id": target.id,
            "updated_at": updated_at,
            "sheets": [item["title"] for item in payload],
        }
        log_step(job_run=job_run, level=JobLog.Level.INFO, message="Report update succeeded", context=report)
        return report
    except Exception as exc:  # noqa: BLE001
        report = {"status": "failed", "target_id": target.id, "error": str(exc)}
        log_step(job_run=job_run, level=JobLog.Level.ERROR, message="Report update failed", context=report)
        return report
