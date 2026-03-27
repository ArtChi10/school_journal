import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from openpyxl import Workbook

from jobs.models import JobRun
from journal_links.models import ClassSheetLink
from validation.job_runner import run_validation_job

ALLOWED_DESCRIPTOR = "Выполняет самостоятельно | Independent"


def _build_valid_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Grade5A"

    ws.cell(row=5, column=1, value="Имя")
    ws.cell(row=5, column=2, value="Фамилия")
    ws.cell(row=5, column=3, value="Критерий 1")
    ws.cell(row=5, column=4, value="Тест 1")
    ws.cell(row=5, column=5, value="Комментарий")
    ws.cell(row=5, column=6, value="Пересдача")

    ws.cell(row=7, column=1, value="Иван")
    ws.cell(row=7, column=2, value="Иванов")
    ws.cell(row=7, column=3, value=ALLOWED_DESCRIPTOR)
    ws.cell(row=7, column=4, value=95)
    ws.cell(row=7, column=5, value="ok")
    ws.cell(row=7, column=6, value="no")

    wb.save(path)


class RunValidationJobTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.link = ClassSheetLink.objects.create(
            class_code="5A",
            subject_name="Math",
            teacher_name="Teacher",
            google_sheet_url="https://docs.google.com/spreadsheets/d/abc123/edit#gid=0",
            is_active=True,
        )

    def test_run_validation_job_creates_jobrun_logs_and_result_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "valid.xlsx"
            _build_valid_workbook(workbook_path)

            with patch("validation.job_runner.fetch_workbook_for_link", return_value=workbook_path):
                job_run = run_validation_job(link_id=self.link.id)

        self.assertEqual(job_run.job_type, "validation")
        self.assertEqual(job_run.status, JobRun.Status.SUCCESS)
        self.assertIsNotNone(job_run.started_at)
        self.assertIsNotNone(job_run.finished_at)

        self.assertIn("summary", job_run.result_json)
        self.assertIn("issues", job_run.result_json)
        self.assertIn("tables", job_run.result_json)
        self.assertEqual(job_run.result_json["summary"]["tables_total"], 1)
        self.assertEqual(job_run.result_json["summary"]["tables_success"], 1)
        self.assertGreaterEqual(job_run.logs.count(), 2)

    def test_command_requires_single_selector(self):
        with self.assertRaises(CommandError):
            call_command("run_validation")

        with self.assertRaises(CommandError):
            call_command("run_validation", "--all-active", "--class-code", "5A")