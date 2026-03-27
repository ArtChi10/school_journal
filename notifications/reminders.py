from collections import Counter, defaultdict

from jobs.models import JobLog, JobRun
from jobs.services import log_step

from .models import TeacherContact
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


def _resolve_contact(teacher_name: str) -> tuple[TeacherContact | None, str | None]:
    contact = TeacherContact.objects.filter(name=teacher_name).first()
    if not contact:
        return None, "no_contact"
    if not contact.is_active:
        return None, "inactive"
    if not _clean_str(contact.chat_id):
        return None, "no_chat_id"
    return contact, None


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

        try:
            send_telegram(contact.chat_id, text, retries=1, job_run_id=job_run.id)
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
    return summary