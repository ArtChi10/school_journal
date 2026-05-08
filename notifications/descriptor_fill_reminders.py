from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from django.db.models import Q
from django.utils import timezone

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from journal_links.descriptor_fill_report import MAX_TEACHER_NAME_LENGTH, REPORT_JOB_TYPE, rows_from_job_run
from notifications.models import NotificationEvent, TeacherContact
from notifications.services import send_telegram

JOB_TYPE = "descriptor_fill_reminders"
logger = logging.getLogger(__name__)


def _clean_str(value: object) -> str:
    return "" if value is None else str(value).strip()


def _db_teacher_name(value: object) -> str:
    return _clean_str(value)[:MAX_TEACHER_NAME_LENGTH]


def _log(job_run: JobRun, level: str, message: str, context: dict | None = None) -> None:
    log_step(job_run=job_run, level=level, message=message, context=context)


def _problem_item(row: dict[str, Any]) -> dict[str, str]:
    item = {
        "class_code": row["class_code"],
        "subject_name": row["subject_name"],
        "module_number": row["module_number"],
        "sheet_url": row["sheet_url"],
    }
    if row.get("grades_missing"):
        item["grades_missing"] = str(row["grades_missing"])
    return item


def _group_rows_by_teacher(rows: list[dict[str, Any]]) -> tuple[dict[str, dict], int]:
    grouped: dict[str, dict] = {}
    skipped_no_teacher = 0

    for row in rows:
        if not row["has_problem"]:
            continue

        teacher_name = _clean_str(row.get("raw_teacher_name"))
        if not teacher_name:
            skipped_no_teacher += 1
            continue

        teacher_payload = grouped.setdefault(
            teacher_name,
            {
                "teacher_name": teacher_name,
                "descriptors": [],
                "criteria": [],
                "grades": [],
            },
        )
        if row["descriptor_problem"]:
            teacher_payload["descriptors"].append(_problem_item(row))
        if row["criteria_problem"]:
            teacher_payload["criteria"].append(_problem_item(row))
        if row["grades_problem"]:
            teacher_payload["grades"].append(_problem_item(row))

    return grouped, skipped_no_teacher


def _payload_hash(payload: dict) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _section_lines(title: str, items: list[dict[str, str]]) -> list[str]:
    if not items:
        return []
    lines = [f"{title}:"]
    for item in items:
        line = f"- {item['class_code']}, {item['subject_name']}, модуль {item['module_number']}"
        if item.get("grades_missing"):
            line = f"{line} (не хватает оценок: {item['grades_missing']})"
        lines.append(line)
    return lines


def _unique_sheet_urls(payload: dict) -> list[str]:
    urls = []
    seen = set()
    for key in ("descriptors", "criteria", "grades"):
        for item in payload[key]:
            url = _clean_str(item.get("sheet_url"))
            if url and url not in seen:
                urls.append(url)
                seen.add(url)
    return urls


def build_descriptor_fill_reminder_message(payload: dict) -> str:
    teacher_name = payload["teacher_name"]
    lines = [
        f"Здравствуйте, {teacher_name}.",
        "",
        "По последней проверке заполненности есть пункты, которые нужно поправить.",
        "",
    ]
    lines.extend(_section_lines("Дескрипторы", payload["descriptors"]))
    if payload["descriptors"]:
        lines.append("")
    lines.extend(_section_lines("Критерии", payload["criteria"]))
    if payload["criteria"]:
        lines.append("")
    lines.extend(_section_lines("Оценки", payload["grades"]))
    if payload["grades"]:
        lines.append("")

    lines.append("Пожалуйста, заполните недостающие данные в таблицах.")
    sheet_urls = _unique_sheet_urls(payload)
    if sheet_urls:
        lines.append("")
        lines.append("Таблицы:")
        for url in sheet_urls:
            lines.append(f"Таблица: {url}")
    return "\n".join(lines).strip()


def _resolve_contact(teacher_name: str) -> tuple[TeacherContact | None, str | None]:
    contact = TeacherContact.objects.filter(name=teacher_name).first()
    if not contact:
        contact = TeacherContact.objects.filter(name__iexact=teacher_name).first()
    if not contact:
        return None, "skipped_no_contact"
    if not contact.is_active:
        return None, "skipped_no_contact"
    if not _clean_str(contact.chat_id):
        return None, "skipped_no_contact"
    return contact, None


def _append_missing_contact(summary: dict[str, Any], teacher_name: str) -> None:
    missing_contacts = summary.setdefault("missing_contacts", [])
    display_name = _db_teacher_name(teacher_name)
    if display_name and display_name not in missing_contacts:
        missing_contacts.append(display_name)


def _already_sent(source_job_run: JobRun, *, teacher_name: str, payload_hash: str) -> bool:
    reminder_job_ids = JobRun.objects.filter(
        Q(id=source_job_run.id)
        | Q(job_type=JOB_TYPE, params_json__source_job_run_id=str(source_job_run.id))
    ).values_list("id", flat=True)
    return NotificationEvent.objects.filter(
        job_run_id__in=reminder_job_ids,
        teacher_name=teacher_name,
        channel=NotificationEvent.Channel.TELEGRAM,
        payload_hash=payload_hash,
        status=NotificationEvent.Status.SENT,
    ).exists()


def _record_notification_event(
    job_run: JobRun,
    *,
    teacher_name: str,
    status: str,
    payload_hash: str,
    error_message: str = "",
) -> None:
    NotificationEvent.objects.create(
        job_run=job_run,
        teacher_name=_db_teacher_name(teacher_name),
        channel=NotificationEvent.Channel.TELEGRAM,
        status=status,
        payload_hash=payload_hash,
        error_message=error_message,
    )


def _teacher_result(payload: dict, *, status: str, reason: str = "") -> dict[str, Any]:
    return {
        "teacher_name": payload["teacher_name"],
        "status": status,
        "reason": reason,
        "descriptor_count": len(payload["descriptors"]),
        "criteria_count": len(payload["criteria"]),
        "grades_count": len(payload["grades"]),
    }


def send_descriptor_fill_reminders(source_job_run: JobRun, *, initiated_by=None) -> JobRun:
    if source_job_run.job_type != REPORT_JOB_TYPE:
        raise ValueError("Source JobRun must be descriptor_criteria_fill_check")

    reminder_job = JobRun.objects.create(
        job_type=JOB_TYPE,
        status=JobRun.Status.RUNNING,
        started_at=timezone.now(),
        initiated_by=initiated_by,
        params_json={
            "source_job_run_id": str(source_job_run.id),
            "trigger": "manual",
        },
        result_json={"summary": {}, "teachers": []},
    )
    _log(
        reminder_job,
        JobLog.Level.INFO,
        "Descriptor fill reminders started",
        {"source_job_run_id": str(source_job_run.id)},
    )

    summary = {
        "teachers_total": 0,
        "sent": 0,
        "skipped_no_teacher": 0,
        "skipped_no_contact": 0,
        "skipped_duplicate": 0,
        "failed": 0,
        "missing_contacts": [],
    }
    teacher_results = []

    try:
        rows = rows_from_job_run(source_job_run)
        grouped_by_teacher, skipped_no_teacher = _group_rows_by_teacher(rows)
        summary["teachers_total"] = len(grouped_by_teacher)
        summary["skipped_no_teacher"] = skipped_no_teacher

        for teacher_name in sorted(grouped_by_teacher):
            payload = grouped_by_teacher[teacher_name]
            payload_hash = _payload_hash(payload)
            contact, skip_reason = _resolve_contact(teacher_name)

            if skip_reason:
                summary["skipped_no_contact"] += 1
                _append_missing_contact(summary, teacher_name)
                teacher_results.append(_teacher_result(payload, status="skipped", reason=skip_reason))
                _record_notification_event(
                    reminder_job,
                    teacher_name=teacher_name,
                    status=NotificationEvent.Status.SKIPPED,
                    payload_hash=payload_hash,
                )
                _log(
                    reminder_job,
                    JobLog.Level.WARNING,
                    "Reminder skipped: no contact",
                    {"teacher": teacher_name, "reason": skip_reason},
                )
                continue

            if _already_sent(source_job_run, teacher_name=teacher_name, payload_hash=payload_hash):
                summary["skipped_duplicate"] += 1
                teacher_results.append(_teacher_result(payload, status="skipped", reason="skipped_duplicate"))
                _record_notification_event(
                    reminder_job,
                    teacher_name=teacher_name,
                    status=NotificationEvent.Status.SKIPPED,
                    payload_hash=payload_hash,
                )
                _log(
                    reminder_job,
                    JobLog.Level.INFO,
                    "Reminder skipped: duplicate",
                    {"teacher": teacher_name},
                )
                continue

            message = build_descriptor_fill_reminder_message(payload)
            try:
                send_telegram(contact.chat_id, message, retries=1, job_run_id=reminder_job.id)
            except Exception as exc:
                summary["failed"] += 1
                error_message = str(exc) or exc.__class__.__name__
                teacher_results.append(_teacher_result(payload, status="error", reason=error_message))
                _record_notification_event(
                    reminder_job,
                    teacher_name=teacher_name,
                    status=NotificationEvent.Status.ERROR,
                    payload_hash=payload_hash,
                    error_message=error_message,
                )
                _log(
                    reminder_job,
                    JobLog.Level.ERROR,
                    "Reminder failed",
                    {"teacher": teacher_name, "error": error_message},
                )
                continue

            summary["sent"] += 1
            teacher_results.append(_teacher_result(payload, status="sent"))
            _record_notification_event(
                reminder_job,
                teacher_name=teacher_name,
                status=NotificationEvent.Status.SENT,
                payload_hash=payload_hash,
            )
            _log(
                reminder_job,
                JobLog.Level.INFO,
                "Reminder sent",
                {"teacher": teacher_name, "chat_id": contact.chat_id},
            )

        if skipped_no_teacher:
            teacher_results.append(
                {
                    "teacher_name": "",
                    "status": "skipped",
                    "reason": "skipped_no_teacher",
                    "descriptor_count": 0,
                    "criteria_count": 0,
                    "grades_count": 0,
                }
            )
            _log(
                reminder_job,
                JobLog.Level.WARNING,
                "Reminder skipped: no teacher",
                {"skipped_no_teacher": skipped_no_teacher},
            )

        reminder_job.status = JobRun.Status.PARTIAL if summary["failed"] else JobRun.Status.SUCCESS
        reminder_job.finished_at = timezone.now()
        reminder_job.result_json = {"summary": summary, "teachers": teacher_results}
        reminder_job.save(update_fields=["status", "finished_at", "result_json"])
        _log(
            reminder_job,
            JobLog.Level.INFO,
            "Descriptor fill reminders finished",
            summary,
        )
    except Exception as exc:
        error_message = str(exc) or exc.__class__.__name__
        summary["failed"] = max(1, int(summary.get("failed", 0) or 0))
        summary["fatal_error"] = error_message
        reminder_job.status = JobRun.Status.FAILED
        reminder_job.finished_at = timezone.now()
        reminder_job.result_json = {
            "summary": summary,
            "teachers": teacher_results,
            "error": error_message,
        }
        reminder_job.save(update_fields=["status", "finished_at", "result_json"])
        _log(
            reminder_job,
            JobLog.Level.ERROR,
            "Descriptor fill reminders failed",
            {"source_job_run_id": str(source_job_run.id), "error": error_message},
        )
        logger.exception(
            "Descriptor fill reminders failed",
            extra={"source_job_run_id": str(source_job_run.id), "reminder_job_id": str(reminder_job.id)},
        )
    return reminder_job
