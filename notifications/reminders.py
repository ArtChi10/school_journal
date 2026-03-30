from collections import defaultdict
import hashlib
import json
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from pipeline.models import CriterionEntry

from .models import NotificationEvent, TeacherContact
from .services import TelegramSendError, send_telegram

TOP_VALID_CRITERIA_LIMIT = 5
TOP_INVALID_CRITERIA_LIMIT = 10



def _log(job_run: JobRun, level: str, message: str, context: dict | None = None) -> None:
    log_step(job_run=job_run, level=level, message=message, context=context)

def _clean_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _entry_location(entry: dict) -> str:
    class_name = _clean_str(entry.get("class_code"))
    subject = _clean_str(entry.get("subject_name"))

    if class_name and subject:
        return f"{class_name} / {subject}"
    if class_name:
        return class_name
    if subject:
        return subject
    return "UNKNOWN"


def _criterion_preview(text: str, max_len: int = 90) -> str:
    value = _clean_str(text)
    if len(value) <= max_len:
        return value
    return f"{value[: max_len - 1]}…"

def _build_teacher_payload(teacher_name: str) -> dict | None:
    entries = list(
        CriterionEntry.objects.filter(teacher_name=teacher_name).order_by(
               "class_code", "subject_name", "module_number", "criterion_text"
        )
    )
    if not entries:
        return None

    checked_entries = [
        entry
        for entry in entries
        if entry.validation_status != CriterionEntry.ValidationStatus.PENDING
        ]
    if not checked_entries:
        return None

    valid_entries: list[dict] = []
    invalid_entries: list[dict] = []
    status_counts: dict[str, int] = defaultdict(int)
    for entry in checked_entries:
        status = _clean_str(entry.validation_status)
        status_counts[status] += 1
        base_item = {
            "class_code": entry.class_code,
            "subject_name": entry.subject_name,
            "module_number": entry.module_number,
            "criterion_text": entry.criterion_text,
            "status": status,
        }
        if status in {
            CriterionEntry.ValidationStatus.VALID,
            CriterionEntry.ValidationStatus.OVERRIDE,
        }:
            valid_entries.append(base_item)
        elif status in {
            CriterionEntry.ValidationStatus.INVALID,
            CriterionEntry.ValidationStatus.RECHECK,
        }:
            invalid_entries.append(
                {
                    **base_item,
                    "ai_fix_suggestion": entry.ai_fix_suggestion,
                    "ai_why": entry.ai_why,
                }
            )
    if not invalid_entries:
        return None

    return {
        "teacher_name": teacher_name,
        "checked_count": len(checked_entries),
        "status_counts": dict(status_counts),
        "valid_entries": valid_entries,
        "invalid_entries": invalid_entries,
    }


def _build_teacher_message(payload: dict) -> str:
    teacher_name = payload["teacher_name"]
    checked_count = payload["checked_count"]
    status_counts = payload["status_counts"]
    valid_entries = payload["valid_entries"]
    invalid_entries = payload["invalid_entries"]

    lines = [
        "Напоминание по критериям журнала",
        f"Преподаватель: {teacher_name}",
        (
            "Проверено критериев: "
            f"{checked_count} "
            f"(valid: {status_counts.get('valid', 0)}, "
            f"override: {status_counts.get('override', 0)}, "
            f"invalid: {status_counts.get('invalid', 0)}, "
            f"recheck: {status_counts.get('recheck', 0)})"
        ),
    ]
    if valid_entries:
        lines.append(f"✅ Хорошие критерии (до {TOP_VALID_CRITERIA_LIMIT}):")
    for entry in valid_entries[:TOP_VALID_CRITERIA_LIMIT]:
        lines.append(
            "• "
            f"{_entry_location(entry)} · M{entry['module_number']} — "
            f"{_criterion_preview(entry['criterion_text'])}"
        )
    lines.append(f"⚠️ Невалидные критерии и как исправить (до {TOP_INVALID_CRITERIA_LIMIT}):")
    for entry in invalid_entries[:TOP_INVALID_CRITERIA_LIMIT]:
        suggestion = _clean_str(entry.get("ai_fix_suggestion")) or _clean_str(entry.get("ai_why"))
    if not suggestion:
        suggestion = "Уточните формулировку критерия и запустите проверку повторно."
    lines.append(
        "• "
        f"{_entry_location(entry)} · M{entry['module_number']} — "
        f"{_criterion_preview(entry['criterion_text'])}"
    )
    lines.append(f"  ↳ Подсказка AI: {_criterion_preview(suggestion, max_len=180)}")

    lines.append("Пожалуйста, исправьте невалидные критерии и подтвердите обновление.")
    return "\n".join(lines)



def _build_admin_summary_payload(
    grouped_by_teacher: dict[str, dict],
    *,
    sent: int,
    skipped: int,
    errors: int,
) -> dict:
    teachers_with_issues: list[dict] = []

    for teacher_name in sorted(grouped_by_teacher):
        payload = grouped_by_teacher[teacher_name]
        invalid_entries = payload["invalid_entries"]

        details = [
            {
                "class_subject": _entry_location(item),
                "module_number": item["module_number"],
                "criterion_text": _criterion_preview(item["criterion_text"]),
                "ai_fix_suggestion": _clean_str(item.get("ai_fix_suggestion")),
            }
            for item in invalid_entries[:TOP_INVALID_CRITERIA_LIMIT]
        ]
        teachers_with_issues.append(
            {
                "teacher": teacher_name,
                "checked_count": payload["checked_count"],
                "invalid_count": len(invalid_entries),
                "details": details,
            }
        )

    return {
        "total_teachers": len(grouped_by_teacher),
        "sent": sent,
        "skipped": skipped,
        "errors": errors,
        "teachers_with_issues": teachers_with_issues,
    }


def _build_admin_summary_text(job_run: JobRun, payload: dict) -> str:
    lines = [
        f"Validation summary (job_id={job_run.id})",
        "",
        "Метрики:",
        f"• всего учителей: {payload['total_teachers']}",
        f"• sent: {payload['sent']}",
        f"• skipped: {payload['skipped']}",
        f"• errors: {payload['errors']}",
        "",
        "Кто требует исправления критериев:",
    ]

    teachers_with_issues = payload.get("teachers_with_issues", [])
    if not teachers_with_issues:
        lines.append("• нет проблемных учителей")
        return "\n".join(lines)

    for teacher_item in teachers_with_issues:
        teacher = teacher_item["teacher"]
        lines.append(
            f"• {teacher} (checked: {teacher_item['checked_count']}, invalid: {teacher_item['invalid_count']})"
        )
        for detail in teacher_item["details"]:
            lines.append(
                "  - "
                f"{detail['class_subject']} · M{detail['module_number']} — {detail['criterion_text']}"
            )
            if detail["ai_fix_suggestion"]:
                lines.append(f"    ↳ AI: {_criterion_preview(detail['ai_fix_suggestion'], max_len=150)}")

    return "\n".join(lines)


def _send_admin_summary(job_run: JobRun, payload: dict) -> None:
    _log(job_run, JobLog.Level.INFO, "Validation admin summary payload", payload)

    admin_chat_id = _clean_str(getattr(settings, "ADMIN_LOG_CHAT_ID", ""))
    if not admin_chat_id:
        _log(
            job_run,
            JobLog.Level.WARNING,
            "ADMIN_LOG_CHAT_ID is not configured; admin summary skipped",
        )
        return

    text = _build_admin_summary_text(job_run, payload)
    try:
        send_telegram(admin_chat_id, text, retries=1, job_run_id=job_run.id)
        _log(
            job_run,
            JobLog.Level.INFO,
            "Admin summary sent",
            {
                "chat_id": admin_chat_id,
                "status": "sent",
            },
        )
    except TelegramSendError as exc:
        _log(
            job_run,
            JobLog.Level.ERROR,
            f"Failed to send admin summary: {exc}",
            {
                "chat_id": admin_chat_id,
                "status": "error",
                "error": str(exc),
            },
        )


def _resolve_contact(teacher_name: str) -> tuple[TeacherContact | None, str | None]:
    contact = TeacherContact.objects.filter(name=teacher_name).first()
    if not contact:
        return None, "no_contact"
    if not contact.is_active:
        return None, "inactive"
    if not _clean_str(contact.chat_id):
        return None, "no_chat_id"
    return contact, None

def _payload_hash(payload: dict) -> str:
    serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()


def _was_already_sent(job_run: JobRun, *, teacher_name: str, payload_hash: str) -> bool:
    source_job_run_id = str((job_run.params_json or {}).get("source_job_run_id") or job_run.id)
    dedupe_job_run_ids = JobRun.objects.filter(
        Q(id=source_job_run_id)
        | Q(job_type="send_validation_reminders", params_json__source_job_run_id=source_job_run_id)
    ).values_list("id", flat=True)
    return NotificationEvent.objects.filter(
        job_run_id__in=dedupe_job_run_ids,
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
) -> None:
    NotificationEvent.objects.create(
        job_run=job_run,
        teacher_name=teacher_name,
        channel=NotificationEvent.Channel.TELEGRAM,
        status=status,
        sent_at=timezone.now(),
        payload_hash=payload_hash,
    )

def _collect_teacher_payloads() -> dict[str, dict]:
    teacher_names = (
        CriterionEntry.objects.exclude(teacher_name="")
        .values_list("teacher_name", flat=True)
        .distinct()
    )
    grouped_by_teacher: dict[str, dict] = {}
    for teacher_name in sorted(teacher_names):
        payload = _build_teacher_payload(teacher_name)
        if payload is not None:
            grouped_by_teacher[teacher_name] = payload
    return grouped_by_teacher


def send_validation_reminders_for_job(job_run: JobRun) -> dict:
    grouped_by_teacher = _collect_teacher_payloads()

    if not grouped_by_teacher:
        _log(job_run, JobLog.Level.INFO, "No teacher-linked invalid criterion payloads for reminders")
        return {"sent": 0, "skipped": 0, "errors": 0}

    sent = 0
    skipped = 0
    errors = 0

    for teacher_name in sorted(grouped_by_teacher):
        teacher_payload = grouped_by_teacher[teacher_name]
        contact, skip_reason = _resolve_contact(teacher_name)
        event_payload_hash = _payload_hash(teacher_payload)

        if skip_reason:
            _record_notification_event(
                job_run,
                teacher_name=teacher_name,
                status=NotificationEvent.Status.SKIPPED,
                payload_hash=event_payload_hash,
            )
            skipped += 1
            _log(
                job_run,
                JobLog.Level.WARNING,
                f"Reminder skipped for {teacher_name}: {skip_reason}",
                {
                    "teacher": teacher_name,
                    "reason": skip_reason,
                     "invalid_count": len(teacher_payload["invalid_entries"]),
                },
            )
            continue

        text = _build_teacher_message(teacher_payload)
        if _was_already_sent(job_run, teacher_name=teacher_name, payload_hash=event_payload_hash):
            _record_notification_event(
                job_run,
                teacher_name=teacher_name,
                status=NotificationEvent.Status.SKIPPED,
                payload_hash=event_payload_hash,
            )
            skipped += 1
            _log(
                job_run,
                JobLog.Level.INFO,
                f"Reminder skipped for {teacher_name}: skipped_duplicate",
                {
                    "teacher": teacher_name,
                    "reason": "skipped_duplicate",
                    "invalid_count": len(teacher_payload["invalid_entries"]),
                },
            )
            continue

        try:
            send_telegram(contact.chat_id, text, retries=1, job_run_id=job_run.id)
            _record_notification_event(
                job_run,
                teacher_name=teacher_name,
                status=NotificationEvent.Status.SENT,
                payload_hash=event_payload_hash,
            )
            sent += 1
            _log(
                job_run,
                JobLog.Level.INFO,
                  f"Reminder sent to {teacher_name}",
                {
                    "teacher": teacher_name,
                    "chat_id": contact.chat_id,
                    "invalid_count": len(teacher_payload["invalid_entries"]),
                },
            )
        except TelegramSendError as exc:
            _record_notification_event(
                job_run,
                teacher_name=teacher_name,
                status=NotificationEvent.Status.ERROR,
                payload_hash=event_payload_hash,
            )
            errors += 1
            _log(
                job_run,
                JobLog.Level.ERROR,
                f"Failed reminder for {teacher_name}: {exc}",
                {
                    "teacher": teacher_name,
                    "chat_id": contact.chat_id,
                    "invalid_count": len(teacher_payload["invalid_entries"]),
                },
            )

    summary = {"sent": sent, "skipped": skipped, "errors": errors}
    _log(job_run, JobLog.Level.INFO, "Validation reminders summary", summary)
    admin_summary_payload = _build_admin_summary_payload(
        grouped_by_teacher,
        sent=sent,
        skipped=skipped,
        errors=errors,
    )
    _send_admin_summary(job_run, admin_summary_payload)
    return summary


def run_validation_reminders_job(*, source_job_run: JobRun, initiated_by=None) -> JobRun:
    issues = (source_job_run.result_json or {}).get("issues", [])
    if not isinstance(issues, list):
        issues = []

    reminder_job = JobRun.objects.create(
        job_type="send_validation_reminders",
        status=JobRun.Status.RUNNING,
        started_at=timezone.now(),
        initiated_by=initiated_by,
        params_json={
            "source_job_run_id": str(source_job_run.id),
        },
        result_json={
            "issues": issues,
        },
    )

    _log(
        reminder_job,
        JobLog.Level.INFO,
        "Reminder job started",
        {"source_job_run_id": str(source_job_run.id), "issues_count": len(issues)},
    )

    try:
        summary = send_validation_reminders_for_job(reminder_job)
        reminder_job.result_json = {
            "issues": issues,
            "source_job_run_id": str(source_job_run.id),
            "summary": summary,
        }
        reminder_job.status = JobRun.Status.PARTIAL if summary.get("errors", 0) > 0 else JobRun.Status.SUCCESS
        return reminder_job
    except Exception as exc:
        _log(
            reminder_job,
            JobLog.Level.ERROR,
            f"Reminder job failed: {exc}",
            {"source_job_run_id": str(source_job_run.id)},
        )
        reminder_job.status = JobRun.Status.FAILED
        reminder_job.result_json = {
            "issues": issues,
            "source_job_run_id": str(source_job_run.id),
            "error": str(exc),
        }
        return reminder_job
    finally:
        reminder_job.finished_at = timezone.now()
        reminder_job.save(update_fields=["status", "finished_at", "result_json"])