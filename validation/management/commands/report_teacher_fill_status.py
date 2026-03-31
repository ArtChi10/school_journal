from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from jobs.models import JobRun
from notifications.services import TelegramSendError, send_telegram
from validation.job_runner import run_validation_job

TARGET_GROUPS = ("descriptor", "criteria", "grades")
GROUP_TITLES = {
    "descriptor": "Дескриптор | Descriptor",
    "criteria": "Критерии",
    "grades": "Оценки учеников",
}


class Command(BaseCommand):
    help = (
        "Build teacher completion report for Descriptor / Criteria / Grades "
        "from validation issues"
    )

    def add_arguments(self, parser):
        parser.add_argument("--job-id", type=str, help="Use existing validation JobRun id")
        parser.add_argument("--run-all-active", action="store_true", help="Run fresh validation for all active links")

    def _render_teacher_with_classes(self, teacher_name: str, classes: list[str]) -> str:
        if not classes:
            return teacher_name
        return f"{teacher_name} ({', '.join(classes)})"

    def _build_report_data(self, job_run: JobRun) -> dict:
        result = job_run.result_json or {}
        tables = result.get("tables", [])
        issues = result.get("issues", [])

        teachers = {
            (table.get("teacher_name") or "").strip()
            for table in tables
            if (table.get("teacher_name") or "").strip()
        }

        issue_teachers_by_group: dict[str, set[str]] = defaultdict(set)
        issue_classes_by_group_teacher: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

        for issue in issues:
            issue_group = (issue.get("issue_group") or "").strip().lower()
            if issue_group not in TARGET_GROUPS:
                continue

            teacher_name = (issue.get("teacher_name") or "").strip()
            if not teacher_name:
                continue

            issue_teachers_by_group[issue_group].add(teacher_name)

            class_code = (issue.get("class_code") or "").strip()
            if class_code:
                issue_classes_by_group_teacher[issue_group][teacher_name].add(class_code)

        by_group: dict[str, dict[str, list[str]]] = {}
        for group in TARGET_GROUPS:
            not_filled_names = sorted(issue_teachers_by_group.get(group, set()))
            filled_names = sorted(teachers - set(not_filled_names))

            not_filled = [
                self._render_teacher_with_classes(
                    teacher_name,
                    sorted(issue_classes_by_group_teacher.get(group, {}).get(teacher_name, set())),
                )
                for teacher_name in not_filled_names
            ]

            by_group[group] = {
                "filled": filled_names,
                "not_filled": not_filled,
            }

        return {
            "job_id": str(job_run.id),
            "status": job_run.status,
            "teachers_total": len(teachers),
            "by_group": by_group,
        }

    def _build_console_text(self, report: dict) -> str:
        lines = [
            f"Validation job: {report['job_id']} (status={report['status']})",
            f"Teachers in scope: {report['teachers_total']}",
        ]

        for group in TARGET_GROUPS:
            filled = report["by_group"][group]["filled"]
            not_filled = report["by_group"][group]["not_filled"]

            lines.append("")
            lines.append(f"=== {GROUP_TITLES[group]} ===")
            lines.append(f"Заполнили ({len(filled)}): {', '.join(filled) if filled else '-'}")
            lines.append(f"Не заполнили ({len(not_filled)}): {', '.join(not_filled) if not_filled else '-'}")

        return "\n".join(lines)

    def _build_telegram_text(self, report: dict) -> str:
        lines = [
            "📊 Отчёт по заполненности журналов",
            f"Job: {report['job_id']}",
            f"Статус: {report['status']}",
            f"Преподавателей в срезе: {report['teachers_total']}",
            "",
        ]

        for group in TARGET_GROUPS:
            filled = report["by_group"][group]["filled"]
            not_filled = report["by_group"][group]["not_filled"]

            lines.append(f"🔹 {GROUP_TITLES[group]}")
            lines.append(f"✅ Заполнили ({len(filled)}): {', '.join(filled) if filled else '-'}")
            lines.append(f"❌ Не заполнили ({len(not_filled)}): {', '.join(not_filled) if not_filled else '-'}")
            lines.append("")

        return "\n".join(lines).strip()

    def _send_to_admin_chat(self, report: dict, *, job_run: JobRun | None = None) -> None:
        admin_chat_id = str(getattr(settings, "ADMIN_LOG_CHAT_ID", "") or "").strip()
        if not admin_chat_id:
            self.stdout.write(self.style.WARNING("ADMIN_LOG_CHAT_ID is not configured; Telegram send skipped"))
            return

        text = self._build_telegram_text(report)
        try:
            send_telegram(admin_chat_id, text, retries=1, job_run_id=job_run.id if job_run else None)
            self.stdout.write(self.style.SUCCESS(f"Telegram report sent to ADMIN_LOG_CHAT_ID={admin_chat_id}"))
        except TelegramSendError as exc:
            raise CommandError(f"Failed to send Telegram report to ADMIN_LOG_CHAT_ID: {exc}") from exc

    def handle(self, *args, **options):
        job_id = options.get("job_id")
        run_all_active = options.get("run_all_active")

        if job_id and run_all_active:
            raise CommandError("Use either --job-id or --run-all-active, not both")

        if run_all_active:
            job_run = run_validation_job(all_active=True)
        elif job_id:
            job_run = JobRun.objects.filter(id=job_id, job_type="validation").first()
            if job_run is None:
                raise CommandError(f"Validation job not found: {job_id}")
        else:
            job_run = JobRun.objects.filter(job_type="validation").order_by("-started_at").first()
            if job_run is None:
                raise CommandError("No validation jobs found. Run `python manage.py run_validation --all-active` first")

        report = self._build_report_data(job_run)
        console_text = self._build_console_text(report)
        self.stdout.write(console_text)

        self._send_to_admin_chat(report, job_run=job_run)