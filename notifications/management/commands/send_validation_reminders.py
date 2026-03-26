from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from jobs.models import JobLog, JobRun
from notifications.models import TeacherContact
from notifications.services import TelegramSendError, send_telegram


class Command(BaseCommand):
    help = "Send grouped Telegram reminders to teachers for a validation job"

    def add_arguments(self, parser):
        parser.add_argument("--job", required=True, type=str, help="JobRun UUID")

    def _log(self, job_run: JobRun, level: str, message: str, context: dict | None = None) -> None:
        JobLog.objects.create(
            job_run=job_run,
            level=level,
            message=message,
            context_json=context or {},
        )

    def _extract_teacher_name(self, issue: dict) -> str | None:
        # Preferred explicit teacher field
        teacher = (issue.get("teacher") or "").strip()
        if teacher:
            return teacher

        # Fallback heuristic: first token before separators in sheet name
        sheet = (issue.get("sheet") or "").strip()
        if not sheet:
            return None

        for sep in ["|", "-", "/", "—", ":"]:
            if sep in sheet:
                maybe = sheet.split(sep)[0].strip()
                if maybe:
                    return maybe

        return sheet

    def handle(self, *args, **options):
        job_id = options["job"]
        try:
            job_run = JobRun.objects.get(id=job_id)
        except JobRun.DoesNotExist as exc:
            raise CommandError(f"JobRun not found: {job_id}") from exc

        issues = (job_run.result_json or {}).get("issues", [])
        if not isinstance(issues, list):
            raise CommandError("JobRun result_json.issues must be a list")

        grouped = defaultdict(list)
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            teacher = self._extract_teacher_name(issue)
            if teacher:
                grouped[teacher].append(issue)

        if not grouped:
            self.stdout.write(self.style.WARNING("No teacher-linked issues found. Nothing to send."))
            self._log(job_run, JobLog.Level.INFO, "No teacher-linked issues for reminders")
            return

        sent = 0
        skipped = 0

        for teacher_name, teacher_issues in grouped.items():
            contact = TeacherContact.objects.filter(name=teacher_name, is_active=True).first()
            if not contact:
                skipped += 1
                msg = f"No active contact for teacher: {teacher_name}. issues={len(teacher_issues)}"
                self.stdout.write(self.style.WARNING(msg))
                self._log(job_run, JobLog.Level.WARNING, msg, {"teacher": teacher_name})
                continue

            critical = sum(1 for i in teacher_issues if i.get("severity") == "critical")
            warning = sum(1 for i in teacher_issues if i.get("severity") == "warning")
            samples = teacher_issues[:3]

            lines = [
                f"Напоминание по валидации модуля.",
                f"Учитель: {teacher_name}",
                f"Проблем: {len(teacher_issues)} (critical: {critical}, warning: {warning})",
                "Примеры:",
            ]

            for issue in samples:
                student = issue.get("student") or "—"
                message = issue.get("message") or issue.get("code") or "Проверьте таблицу"
                lines.append(f"• {student}: {message}")

            lines.append("Пожалуйста, заполните/исправьте таблицу.")
            text = "\n".join(lines)

            try:
                send_telegram(contact.chat_id, text, retries=1)
                sent += 1
                log_msg = f"Reminder sent to {teacher_name} ({contact.chat_id}), issues={len(teacher_issues)}"
                self.stdout.write(self.style.SUCCESS(log_msg))
                self._log(job_run, JobLog.Level.INFO, log_msg, {"teacher": teacher_name})
            except TelegramSendError as exc:
                err = f"Failed to send reminder to {teacher_name}: {exc}"
                self.stdout.write(self.style.ERROR(err))
                self._log(job_run, JobLog.Level.ERROR, err, {"teacher": teacher_name})

        self.stdout.write(self.style.SUCCESS(f"Done. sent={sent}, skipped={skipped}"))