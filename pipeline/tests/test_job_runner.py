import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from openpyxl import Workbook

from jobs.models import JobLog, JobRun
from journal_links.models import ClassSheetLink
from pipeline.job_runner import run_build_criteria_job
from pipeline.services import CriterionNormalizationError
from pipeline.models import CriterionEntry


def _build_workbook(path: Path) -> None:
    wb = Workbook()

    ws_math = wb.active
    ws_math.title = "Math"
    ws_math["C2"] = "Ms. Frizzle"
    ws_math["C3"] = "Module 2"
    ws_math.cell(row=5, column=2, value="Критерии оценивания | \nAssessment criteria")
    ws_math.cell(row=5, column=3, value="Критерий 1")
    ws_math.cell(row=5, column=4, value="Критерий 2")

    ws_history = wb.create_sheet("History")
    ws_history["C2"] = "Mr. History"
    ws_history["C3"] = "3"
    ws_history.cell(row=5, column=2, value="Критерии оценивания | \nAssessment criteria")
    ws_history.cell(row=5, column=3, value="Критерий H1")

    wb.save(path)


class BuildCriteriaJobTests(TestCase):
    def test_run_build_criteria_job_creates_job_logs_and_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "criteria.xlsx"
            _build_workbook(workbook_path)

            ClassSheetLink.objects.create(
                class_code="4A",
                subject_name="Math",
                teacher_name="Teacher A",
                google_sheet_url="https://docs.google.com/spreadsheets/d/test-id/edit#gid=0",
                is_active=True,
            )

            def _fake_ai(text, **_kwargs):
                if text == "Критерий H1":
                    raise CriterionNormalizationError("ai failed")
                return f"AI::{text}"

            with (
                patch("pipeline.job_runner.fetch_workbook_for_link", return_value=workbook_path),
                patch("pipeline.job_runner.normalize_criterion_text_with_ai", side_effect=_fake_ai),
            ):
                job = run_build_criteria_job(class_code="4A")

        self.assertEqual(job.job_type, "build_criteria_table")
        self.assertEqual(job.status, JobRun.Status.PARTIAL)
        self.assertTrue(JobLog.objects.filter(job_run=job).exists())

        summary = job.result_json["summary"]
        self.assertEqual(summary["total_sheets"], 2)
        self.assertEqual(summary["total_criteria"], 3)
        self.assertEqual(summary["ai_ok"], 2)
        self.assertEqual(summary["ai_failed"], 1)

        saved_rows = CriterionEntry.objects.filter(class_code="4A")
        self.assertEqual(saved_rows.count(), 3)
        self.assertEqual(saved_rows.exclude(criterion_text_ai="").count(), 2)

    def test_management_command_supports_class_code(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "criteria.xlsx"
            _build_workbook(workbook_path)

            ClassSheetLink.objects.create(
                class_code="4A",
                subject_name="Math",
                teacher_name="Teacher A",
                google_sheet_url="https://docs.google.com/spreadsheets/d/test-id/edit#gid=0",
                is_active=True,
            )

            with (
                patch("pipeline.job_runner.fetch_workbook_for_link", return_value=workbook_path),
                patch("pipeline.job_runner.normalize_criterion_text_with_ai", return_value="AI"),
            ):
                call_command("build_criteria_table", "--class-code", "4A")

        self.assertTrue(JobRun.objects.filter(job_type="build_criteria_table").exists())