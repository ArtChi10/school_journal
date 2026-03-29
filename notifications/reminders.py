from collections import Counter, defaultdict
import hashlib
import json
from django.conf import settings
from django.utils import timezone

from jobs.models import JobLog, JobRun
from jobs.services import log_step

from .models import NotificationEvent, TeacherContact
from .services import TelegramSendError, send_telegram

TOP_PROBLEMS_LIMIT = 5


def _log(job_run: JobRun, level: str, message: str, context: dict | None = None) -> None:
    log_step(job_run=job_run, level=level, message=message, context=context)

def _clean_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _issue_location(issue: dict) -> str:
    class_name = _clean_str(issue.get("class_code") or issue.get("class"))
    subject = _clean_str(issue.get("subject_name") or issue.get("subject") or issue.get("sheet"))

    if class_name and subject:
        return f"{class_name} / {subject}"
    if class_name:
        return class_name
    if subject:
        return subject
    return "UNKNOWN"


def _issue_problem_text(issue: dict) -> str:
    message = _clean_str(issue.get("message"))
    if message:
        return message

    code = _clean_str(issue.get("code"))
    if code:
        return code

    return "Проверьте заполнение журнала"


def _build_teacher_message(teacher_name: str, teacher_issues: list[dict]) -> str:
    locations = sorted({_issue_location(issue) for issue in teacher_issues})
    problem_counter: Counter[str] = Counter()
    for issue in teacher_issues:
        problem_counter[_issue_problem_text(issue)] += 1
    severity_counter: Counter[str] = Counter(_clean_str(issue.get("severity")) or "unknown" for issue in teacher_issues)

    lines = [
        "Напоминание по валидации журнала",
        f"Преподаватель: {teacher_name}",
        f"Классы/предметы: {', '.join(locations)}",
        (
            "Проблем: "
            f"всего {len(teacher_issues)} "
            f"(critical: {severity_counter.get('critical', 0)}, "
            f"warning: {severity_counter.get('warning', 0)}, "
            f"info: {severity_counter.get('info', 0)})"
        ),
        f"Топ-{TOP_PROBLEMS_LIMIT} проблем:",
    ]
    for problem, count in problem_counter.most_common(TOP_PROBLEMS_LIMIT):
        lines.append(f"• {problem} (x{count})")

    lines.append("Пожалуйста, исправьте и подтвердите.")
    return "\n".join(lines)


def _build_admin_summary_payload(
    grouped_by_teacher: dict[str, list[dict]],
    *,
    sent: int,
    skipped: int,
    errors: int,
) -> dict:
    teachers_with_issues: list[dict] = []

    for teacher_name in sorted(grouped_by_teacher):
        teacher_issues = grouped_by_teacher[teacher_name]
        issue_counter: Counter[tuple[str, str]] = Counter()
        for issue in teacher_issues:
            issue_counter[(_issue_location(issue), _issue_problem_text(issue))] += 1

        details = [
            {
                "class_subject": location,
                "problem": problem,
                "count": count,
            }
            for (location, problem), count in sorted(issue_counter.items())
        ]
        teachers_with_issues.append(
            {
                "teacher": teacher_name,
                "issues_count": len(teacher_issues),
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
        "Кто не заполнил:",
    ]

    teachers_with_issues = payload.get("teachers_with_issues", [])
    if not teachers_with_issues:
        lines.append("• нет проблемных учителей")
        return "\n".join(lines)

    for teacher_item in teachers_with_issues:
        teacher = teacher_item["teacher"]
        issues_count = teacher_item["issues_count"]
        lines.append(f"• {teacher} (проблем: {issues_count})")
        for detail in teacher_item["details"]:
            lines.append(
                "  - "
                f"{detail['class_subject']} — {detail['problem']} "
                f"(x{detail['count']})"
            )

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


def _normalize_issues_for_hash(teacher_issues: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for issue in teacher_issues:
        normalized.append({key: issue[key] for key in sorted(issue)})
    normalized.sort(
        key=lambda issue: json.dumps(issue, ensure_ascii=False, sort_keys=True, default=str),
    )
    return normalized


def _payload_hash(teacher_issues: list[dict]) -> str:
    normalized_issues = _normalize_issues_for_hash(teacher_issues)
    serialized_issues = json.dumps(normalized_issues, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized_issues.encode("utf-8")).hexdigest()


def _was_already_sent(job_run: JobRun, *, teacher_name: str, payload_hash: str) -> bool:
    return NotificationEvent.objects.filter(
        job_run=job_run,
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




def send_validation_reminders_for_job(job_run: JobRun) -> dict:
    issues = (job_run.result_json or {}).get("issues", [])
    if not isinstance(issues, list):
        raise ValueError("JobRun result_json.issues must be a list")

    grouped_by_teacher: dict[str, list[dict]] = defaultdict(list)
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        teacher_name = _clean_str(issue.get("teacher_name"))
        if not teacher_name:
            continue
        grouped_by_teacher[teacher_name].append(issue)

    if not grouped_by_teacher:
        _log(job_run, JobLog.Level.INFO, "No teacher-linked issues for reminders")
        return {"sent": 0, "skipped": 0, "errors": 0}

    sent = 0
    skipped = 0
    errors = 0

    for teacher_name in sorted(grouped_by_teacher):
        teacher_issues = grouped_by_teacher[teacher_name]
        contact, skip_reason = _resolve_contact(teacher_name)

        if skip_reason:
            event_payload_hash = _payload_hash(teacher_issues)
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
                    "issues_count": len(teacher_issues),
                },
            )
            continue

        text = _build_teacher_message(teacher_name, teacher_issues)
        event_payload_hash = _payload_hash(teacher_issues)
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
                    "issues_count": len(teacher_issues),
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
                    "issues_count": len(teacher_issues),
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
                    "issues_count": len(teacher_issues),
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