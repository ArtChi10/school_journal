from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from jobs.models import JobLog, JobRun
from journal_links.models import DescriptorCriteriaReportTarget
from validation.descriptor_criteria_report import (
    ALL_SUBJECTS_SHEET,
    PROBLEMS_SHEET,
    SUMMARY_SHEET,
    build_descriptor_criteria_report_payload,
    extract_spreadsheet_id,
    update_descriptor_criteria_google_report,
)


def _job_run_with_rows(*, status=JobRun.Status.SUCCESS) -> JobRun:
    return JobRun.objects.create(
        job_type="descriptor_criteria_fill_check",
        status=status,
        started_at=timezone.now(),
        finished_at=timezone.now(),
        result_json={
            "summary": {
                "classes_checked": 2,
                "subjects_checked": 2,
                "fully_filled": 1,
                "with_problems": 1,
                "tables_total": 2,
                "tables_success": 2,
                "tables_failed": 0,
                "sheets_total": 4,
                "sheets_checked": 2,
                "sheets_skipped": 2,
            },
            "rows": [
                {
                    "class_code": "7A",
                    "subject_name": "Math",
                    "teacher_name": "Teacher A",
                    "module_number": 1,
                    "descriptor_status": "filled",
                    "criteria_status": "filled",
                    "criteria_filled": 2,
                    "criteria_total": 2,
                    "criteria_missing": 0,
                    "overall_status": "ok",
                    "sheet_url": "https://docs.google.com/spreadsheets/d/source/edit",
                },
                {
                    "class_code": "7B",
                    "subject_name": "Science",
                    "teacher_name": "Teacher B",
                    "module_number": 2,
                    "descriptor_status": "missing",
                    "criteria_status": "missing",
                    "criteria_filled": 1,
                    "criteria_total": 2,
                    "criteria_missing": 1,
                    "overall_status": "problem",
                    "sheet_url": "https://docs.google.com/spreadsheets/d/source/edit",
                },
            ],
        },
    )


class DescriptorCriteriaReportPayloadTests(TestCase):
    def test_extract_spreadsheet_id(self):
        self.assertEqual(
            extract_spreadsheet_id("https://docs.google.com/spreadsheets/d/report123/edit#gid=0"),
            "report123",
        )

    def test_builds_summary_problems_all_and_class_sheets(self):
        job_run = _job_run_with_rows()

        payload = build_descriptor_criteria_report_payload(job_run)
        titles = [item["title"] for item in payload]

        self.assertIn(SUMMARY_SHEET, titles)
        self.assertIn(PROBLEMS_SHEET, titles)
        self.assertIn(ALL_SUBJECTS_SHEET, titles)
        self.assertIn("7A", titles)
        self.assertIn("7B", titles)

        problems = next(item for item in payload if item["title"] == PROBLEMS_SHEET)
        self.assertEqual(len(problems["values"]), 2)
        self.assertIn("Science", problems["values"][1])


class DescriptorCriteriaReportUpdateTests(TestCase):
    def test_skips_when_no_active_target(self):
        job_run = _job_run_with_rows()

        report = update_descriptor_criteria_google_report(job_run)

        self.assertEqual(report["status"], "not_configured")
        self.assertTrue(JobLog.objects.filter(job_run=job_run, message="Report update skipped").exists())

    @patch("validation.descriptor_criteria_report._write_payload")
    @patch("validation.descriptor_criteria_report._build_sheets_service", return_value=Mock())
    def test_updates_existing_target(self, mocked_service, mocked_write):
        target = DescriptorCriteriaReportTarget.objects.create(
            name="Report",
            google_sheet_url="https://docs.google.com/spreadsheets/d/report123/edit",
            is_active=True,
        )
        job_run = _job_run_with_rows()

        report = update_descriptor_criteria_google_report(job_run)

        self.assertEqual(report["status"], "updated")
        self.assertEqual(report["target_id"], target.id)
        mocked_service.assert_called_once()
        mocked_write.assert_called_once()
        self.assertTrue(JobLog.objects.filter(job_run=job_run, message="Report update succeeded").exists())

    @patch("validation.descriptor_criteria_report._write_payload", side_effect=RuntimeError("insufficient scopes"))
    @patch("validation.descriptor_criteria_report._build_sheets_service", return_value=Mock())
    def test_report_failure_is_returned_without_raising(self, _mocked_service, _mocked_write):
        target = DescriptorCriteriaReportTarget.objects.create(
            name="Report",
            google_sheet_url="https://docs.google.com/spreadsheets/d/report123/edit",
            is_active=True,
        )
        job_run = _job_run_with_rows()

        report = update_descriptor_criteria_google_report(job_run)

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["target_id"], target.id)
        self.assertIn("insufficient scopes", report["error"])
        self.assertTrue(JobLog.objects.filter(job_run=job_run, message="Report update failed").exists())
