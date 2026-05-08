from __future__ import annotations

from datetime import timezone as datetime_timezone
from typing import Any
from zoneinfo import ZoneInfo

from django.utils import timezone

from jobs.models import JobRun
from validation.descriptor_criteria_fill import JOB_TYPE

REPORT_JOB_TYPE = JOB_TYPE
REPORT_STATUSES = [JobRun.Status.SUCCESS, JobRun.Status.PARTIAL, JobRun.Status.FAILED]
REPORT_STATUS_VALUES = {str(status) for status in REPORT_STATUSES}
RECENT_RUN_LIMIT = 50
TBILISI_TZ = ZoneInfo("Asia/Tbilisi")

GRADE_OK_STATUSES = {"ok", "filled", "not_applicable"}
PROBLEM_TYPES = {
    "descriptor": "дескриптор",
    "criteria": "критерии",
    "grades": "оценки",
}
PROBLEM_TYPE_CHOICES = [
    ("descriptor", "Дескриптор"),
    ("criteria", "Критерии"),
    ("grades", "Оценки"),
]
STATUS_CHOICES = [
    (JobRun.Status.SUCCESS, "Успешно"),
    (JobRun.Status.PARTIAL, "Частично"),
    (JobRun.Status.FAILED, "Ошибка"),
]
CSV_HEADERS = [
    "Тип проблемы",
    "Учитель",
    "Класс",
    "Предмет",
    "Модуль",
    "Статус дескриптора",
    "Статус критериев",
    "Оценки",
    "Не хватает оценок",
    "Ссылка",
]


def clean_value(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def descriptor_status_label(value: Any) -> str:
    return {
        "filled": "Заполнен",
        "missing": "Не заполнен",
        "not_found": "Не найден",
    }.get(clean_value(value).lower(), clean_value(value) or "—")


def criteria_status_label(value: Any) -> str:
    return {
        "filled": "Заполнены",
        "missing": "Не заполнены",
        "not_found": "Не найдены",
    }.get(clean_value(value).lower(), clean_value(value) or "—")


def grades_status_label(value: Any) -> str:
    return {
        "ok": "Заполнены",
        "filled": "Заполнены",
        "missing": "Не заполнены",
        "not_applicable": "Не применимо",
    }.get(clean_value(value).lower(), clean_value(value) or "—")


def job_status_label(value: Any) -> str:
    return {
        "success": "Успешно",
        "partial": "Частично",
        "failed": "Ошибка",
    }.get(clean_value(value).lower(), clean_value(value) or "—")


def trigger_label(value: Any) -> str:
    return {
        "manual": "Ручной",
        "scheduled": "Автоматический",
    }.get(clean_value(value).lower(), clean_value(value) or "—")


def format_tbilisi_datetime(value) -> str:
    if value is None:
        return "—"
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone=datetime_timezone.utc)
    return value.astimezone(TBILISI_TZ).strftime("%d.%m.%Y %H:%M (Тбилиси)")


def normalize_report_row(row: dict[str, Any]) -> dict[str, Any]:
    descriptor_status = clean_value(row.get("descriptor_status")).lower()
    criteria_status = clean_value(row.get("criteria_status")).lower()
    grades_status = clean_value(row.get("grades_status")).lower()
    teacher_name = clean_value(row.get("teacher_name")) or "—"
    module_number = row.get("module_number")
    normalized = {
        "teacher_name": teacher_name,
        "class_code": clean_value(row.get("class_code")) or "—",
        "subject_name": clean_value(row.get("subject_name")) or "—",
        "module_number": "—" if module_number is None else clean_value(module_number),
        "descriptor_status": descriptor_status,
        "descriptor_status_label": descriptor_status_label(descriptor_status),
        "criteria_status": criteria_status,
        "criteria_status_label": criteria_status_label(criteria_status),
        "criteria_missing": _int_value(row.get("criteria_missing")),
        "criteria_total": _int_value(row.get("criteria_total")),
        "grades_status": grades_status,
        "grades_status_label": grades_status_label(grades_status),
        "grades_missing": _int_value(row.get("grades_missing")),
        "grades_ratio": clean_value(row.get("grades_ratio")) or "—",
        "sheet_url": clean_value(row.get("sheet_url")),
    }
    normalized["descriptor_problem"] = normalized["descriptor_status"] != "filled"
    normalized["criteria_problem"] = normalized["criteria_status"] != "filled"
    normalized["grades_problem"] = normalized["grades_status"] not in GRADE_OK_STATUSES
    normalized["has_problem"] = (
        normalized["descriptor_problem"] or normalized["criteria_problem"] or normalized["grades_problem"]
    )
    return normalized


def rows_from_job_run(job_run: JobRun | None) -> list[dict[str, Any]]:
    if job_run is None or not isinstance(job_run.result_json, dict):
        return []
    rows = job_run.result_json.get("rows", [])
    if not isinstance(rows, list):
        return []
    return [normalize_report_row(row) for row in rows if isinstance(row, dict)]


def filter_rows(rows: list[dict[str, Any]], *, class_code: str = "", teacher: str = "") -> list[dict[str, Any]]:
    filtered = rows
    if class_code:
        filtered = [row for row in filtered if row["class_code"] == class_code]
    if teacher:
        filtered = [row for row in filtered if row["teacher_name"] == teacher]
    return filtered


def problem_type_allowed(problem_type: str, expected: str) -> bool:
    return problem_type not in PROBLEM_TYPES or problem_type == expected


def descriptor_problem_rows(rows: list[dict[str, Any]], problem_type: str = "") -> list[dict[str, Any]]:
    if not problem_type_allowed(problem_type, "descriptor"):
        return []
    return [row for row in rows if row["descriptor_problem"]]


def criteria_problem_rows(rows: list[dict[str, Any]], problem_type: str = "") -> list[dict[str, Any]]:
    if not problem_type_allowed(problem_type, "criteria"):
        return []
    return [row for row in rows if row["criteria_problem"]]


def grades_problem_rows(rows: list[dict[str, Any]], problem_type: str = "") -> list[dict[str, Any]]:
    if not problem_type_allowed(problem_type, "grades"):
        return []
    return [row for row in rows if row["grades_problem"]]


def filter_options(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "classes": sorted({row["class_code"] for row in rows if row["class_code"] != "—"}),
        "teachers": sorted({row["teacher_name"] for row in rows}),
    }


def build_summary(job_run: JobRun | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    payload_summary = {}
    params = {}
    if job_run is not None and isinstance(job_run.result_json, dict):
        possible_summary = job_run.result_json.get("summary", {})
        if isinstance(possible_summary, dict):
            payload_summary = possible_summary
    if job_run is not None and isinstance(job_run.params_json, dict):
        params = job_run.params_json

    classes = {row["class_code"] for row in rows if row["class_code"] != "—"}
    return {
        "started_at": format_tbilisi_datetime(job_run.started_at) if job_run else "—",
        "trigger": trigger_label(params.get("trigger") if job_run else ""),
        "status": job_status_label(job_run.status) if job_run else "—",
        "classes_checked": len(classes) if rows else _int_value(payload_summary.get("classes_checked")),
        "subjects_checked": len(rows) if rows else _int_value(payload_summary.get("subjects_checked")),
        "fully_filled": sum(1 for row in rows if not row["has_problem"])
        if rows
        else _int_value(payload_summary.get("fully_filled")),
        "with_problems": sum(1 for row in rows if row["has_problem"])
        if rows
        else _int_value(payload_summary.get("with_problems")),
        "descriptors_missing": sum(1 for row in rows if row["descriptor_problem"]),
        "criteria_missing": sum(1 for row in rows if row["criteria_problem"]),
        "grades_missing": sum(1 for row in rows if row["grades_problem"]),
    }


def build_teacher_groups(rows: list[dict[str, Any]], problem_type: str = "") -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        teacher = row["teacher_name"]
        group = groups.setdefault(
            teacher,
            {
                "teacher_name": teacher,
                "descriptor_count": 0,
                "criteria_count": 0,
                "grades_count": 0,
                "total": 0,
            },
        )
        if problem_type_allowed(problem_type, "descriptor") and row["descriptor_problem"]:
            group["descriptor_count"] += 1
        if problem_type_allowed(problem_type, "criteria") and row["criteria_problem"]:
            group["criteria_count"] += 1
        if problem_type_allowed(problem_type, "grades") and row["grades_problem"]:
            group["grades_count"] += 1

    for group in groups.values():
        group["total"] = group["descriptor_count"] + group["criteria_count"] + group["grades_count"]
    return sorted(
        (group for group in groups.values() if group["total"] > 0),
        key=lambda group: (-group["total"], group["teacher_name"].lower()),
    )


def build_problem_export_rows(rows: list[dict[str, Any]], problem_type: str = "") -> list[dict[str, str]]:
    export_rows: list[dict[str, str]] = []
    for row in rows:
        if problem_type_allowed(problem_type, "descriptor") and row["descriptor_problem"]:
            export_rows.append(_csv_row("Дескриптор", row))
        if problem_type_allowed(problem_type, "criteria") and row["criteria_problem"]:
            export_rows.append(_csv_row("Критерии", row))
        if problem_type_allowed(problem_type, "grades") and row["grades_problem"]:
            export_rows.append(_csv_row("Оценки", row))
    return export_rows


def _csv_row(problem_label: str, row: dict[str, Any]) -> dict[str, str]:
    return {
        "Тип проблемы": problem_label,
        "Учитель": row["teacher_name"],
        "Класс": row["class_code"],
        "Предмет": row["subject_name"],
        "Модуль": row["module_number"],
        "Статус дескриптора": row["descriptor_status_label"],
        "Статус критериев": row["criteria_status_label"],
        "Оценки": row["grades_status_label"],
        "Не хватает оценок": str(row["grades_missing"] or ""),
        "Ссылка": row["sheet_url"],
    }


def run_choice_label(job_run: JobRun) -> str:
    return f"{format_tbilisi_datetime(job_run.started_at)} — {job_status_label(job_run.status)}"
