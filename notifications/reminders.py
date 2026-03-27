from collections import defaultdict

from jobs.models import JobLog, JobRun
from jobs.services import log_step

from .models import TeacherContact
from .services import TelegramSendError, send_telegram


def _log(job_run: JobRun, level: str, message: str, context: dict | None = None) -> None:
    log_step(job_run=job_run, level=level, message=message, context=context)


def _teacher_name_candidates(sheet_name: str) -> list[str]:
    raw = (sheet_name or "").strip()
    if not raw:
        return []

    candidates: list[str] = [raw]
    for sep in ["|", "—", "-", "/", ":"]:
        if sep in raw:
            parts = [p.strip() for p in raw.split(sep) if p.strip()]
            if parts:
                # Usually teacher is the last part in "subject | teacher"
                candidates.extend([parts[-1], parts[0]])

    # uniq, keep order
    uniq: list[str] = []
    for c in candidates:
        if c and c not in uniq:
            uniq.append(c)
    return uniq


def _find_contact_by_sheet(sheet_name: str) -> tuple[str, TeacherContact | None]:
    for candidate in _teacher_name_candidates(sheet_name):
        contact = TeacherContact.objects.filter(name=candidate, is_active=True).first()
        if contact:
            return candidate, contact
    return sheet_name, None


def send_validation_reminders_for_job(job_run: JobRun) -> dict:
    issues = (job_run.result_json or {}).get("issues", [])
    if not isinstance(issues, list):
        raise ValueError("JobRun result_json.issues must be a list")

    grouped_by_sheet: dict[str, list[dict]] = defaultdict(list)
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        sheet = (issue.get("sheet") or "UNKNOWN").strip() or "UNKNOWN"
        grouped_by_sheet[sheet].append(issue)

    if not grouped_by_sheet:
        _log(job_run, JobLog.Level.INFO, "No sheet-linked issues for reminders")
        return {"sent": 0, "skipped": 0, "errors": 0}

    sent = 0
    skipped = 0
    errors = 0

    for sheet_name, sheet_issues in grouped_by_sheet.items():
        teacher_name, contact = _find_contact_by_sheet(sheet_name)

        if not contact:
            skipped += 1
            msg = f"Teacher contact not found for sheet '{sheet_name}'"
            _log(job_run, JobLog.Level.WARNING, msg, {"sheet": sheet_name, "teacher": teacher_name})
            continue

        critical = sum(1 for i in sheet_issues if i.get("severity") == "critical")
        warning = sum(1 for i in sheet_issues if i.get("severity") == "warning")

        lines = [
            "Напоминание по заполнению",
            f"Лист: {sheet_name}",
            f"Критичных: {critical}, предупреждений: {warning}",
            "Топ-3 проблемы:",
        ]

        for issue in sheet_issues[:3]:
            short = issue.get("message") or issue.get("code") or "Проверьте заполнение"
            student = issue.get("student") or "—"
            lines.append(f"• {student}: {short}")

        text = "\n".join(lines)

        try:
            send_telegram(contact.chat_id, text, retries=1)
            sent += 1
            _log(
                job_run,
                JobLog.Level.INFO,
                f"Reminder sent for sheet '{sheet_name}' to {teacher_name}",
                {"sheet": sheet_name, "teacher": teacher_name, "chat_id": contact.chat_id},
            )
        except TelegramSendError as exc:
            errors += 1
            _log(
                job_run,
                JobLog.Level.ERROR,
                f"Failed reminder for sheet '{sheet_name}': {exc}",
                {"sheet": sheet_name, "teacher": teacher_name, "chat_id": contact.chat_id},
            )

    return {"sent": sent, "skipped": skipped, "errors": errors}