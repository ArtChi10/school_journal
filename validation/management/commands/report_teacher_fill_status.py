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
ISSUE_GROUP_BY_CODE = {
    "DESCRIPTOR_EMPTY": "descriptor",
    "CRITERIA_HEADERS_EMPTY": "criteria",
    "GRADE_EMPTY": "grades",
}
VALIDATION_JOB_TYPES = ("run_validation", "validation")
INVALID_TEACHER_NAMES = {"n/a", "na", "unknown", "none", "null", "-", "—"}

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
        tables = self._iter_dict_items(result.get("tables"))
        issues = self._iter_dict_items(result.get("issues"))
        teachers = set()
        for table in tables:
            teacher_name = self._normalize_teacher_name(table.get("teacher_name"))
            if teacher_name:
                teachers.add(teacher_name)
        issue_teachers_by_group: dict[str, set[str]] = defaultdict(set)
        issue_classes_by_group_teacher: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

        for issue in issues:
            issue_group = self._resolve_issue_group(issue)
            if issue_group not in TARGET_GROUPS:
                continue
            teacher_name = self._normalize_teacher_name(issue.get("teacher_name"))
            if not teacher_name:
                continue
            teachers.add(teacher_name)
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

    def _iter_dict_items(self, payload: object) -> list[dict]:
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _resolve_issue_group(self, issue: dict) -> str:
        issue_group = (issue.get("issue_group") or "").strip().lower()
        if issue_group:
            return issue_group

        code = (issue.get("code") or "").strip()
        return ISSUE_GROUP_BY_CODE.get(code, "")

    def _normalize_teacher_name(self, teacher_name: object) -> str:
        value = str(teacher_name or "").strip()
        if not value:
            return ""
        if value.lower() in INVALID_TEACHER_NAMES:
            return ""
        return value

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

