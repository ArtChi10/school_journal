from datetime import datetime, timezone as datetime_timezone
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from jobs.models import JobLog, JobRun
from pipeline.ai_criteria_report import (
    AI_REPORT_HEADERS,
    ALL_CRITERIA_SHEET,
    PROBLEMS_SHEET,
    SUMMARY_SHEET,
    build_ai_criteria_report_payload,
    update_ai_criteria_google_report,
    _write_payload,
)
from pipeline.models import AICriteriaReportTarget


def _job_run_with_ai_rows(*, status=JobRun.Status.SUCCESS) -> JobRun:
    return JobRun.objects.create(
        job_type="ai_criteria_class_review",
        status=status,
        started_at=timezone.now(),
        finished_at=timezone.now(),
        result_json={
            "summary": {
                "classes_checked": 1,
                "criteria_sent_to_ai": 2,
                "criteria_skipped_empty": 1,
                "criteria_skipped_numeric": 1,
                "criteria_ok": 1,
                "criteria_problem": 1,
                "ai_requests_total": 1,
                "ai_requests_failed": 0,
            },
            "rows": [
                {
                    "class_code": "7A",
                    "subject_name": "Math",
                    "teacher_name": "Teacher A",
                    "module_number": 1,
                    "criterion_text": "Solves equations",
                    "ai_verdict": "ok",
                    "ai_reason": "Clear",
                    "ai_suggested_rewrite": "",
                    "sheet_url": "https://docs.google.com/spreadsheets/d/source/edit",
                },
                {
                    "class_code": "7A",
                    "subject_name": "Science",
                    "teacher_name": "Teacher B",
                    "module_number": 2,
                    "criterion_text": "Knows topic",
                    "ai_verdict": "problem",
                    "ai_reason": "Too broad",
                    "ai_suggested_rewrite": "Explains the topic with evidence.",
                    "sheet_url": "https://docs.google.com/spreadsheets/d/source/edit",
                },
            ],
        },
    )


class AICriteriaReportTargetTests(TestCase):
    def test_active_target_is_singleton(self):
        first = AICriteriaReportTarget.objects.create(
            name="First",
            google_sheet_url="https://docs.google.com/spreadsheets/d/first/edit",
            is_active=True,
        )
        second = AICriteriaReportTarget.objects.create(
            name="Second",
            google_sheet_url="https://docs.google.com/spreadsheets/d/second/edit",
            is_active=True,
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)


class AICriteriaReportPayloadTests(TestCase):
    def test_builds_summary_problems_all_and_class_sheets_with_russian_headers(self):
        job_run = _job_run_with_ai_rows()

        payload = build_ai_criteria_report_payload(job_run, report_status="updated", report_updated_at="6 мая 2026, 09:39:49 (Тбилиси)")
        titles = [item["title"] for item in payload]

        self.assertIn(SUMMARY_SHEET, titles)
        self.assertIn(PROBLEMS_SHEET, titles)
        self.assertIn(ALL_CRITERIA_SHEET, titles)
        self.assertIn("7A", titles)

        all_criteria = next(item for item in payload if item["title"] == ALL_CRITERIA_SHEET)
        self.assertEqual(all_criteria["values"][0], AI_REPORT_HEADERS)
        self.assertIn("Критерий преподавателя", all_criteria["values"][0])
        self.assertIn("Оценка AI", all_criteria["values"][0])
        self.assertIn("Открыть", all_criteria["values"][1])
        self.assertEqual(
            all_criteria["hyperlinks"][0],
            {"row_index": 1, "column_index": AI_REPORT_HEADERS.index("Ссылка на таблицу"), "url": "https://docs.google.com/spreadsheets/d/source/edit"},
        )

        problems = next(item for item in payload if item["title"] == PROBLEMS_SHEET)
        self.assertEqual(len(problems["values"]), 2)
        self.assertIn("Knows topic", problems["values"][1])
        summary = next(item for item in payload if item["title"] == SUMMARY_SHEET)
        self.assertIn(["Google-отчет обновлен", "6 мая 2026, 09:39:49 (Тбилиси)"], summary["values"])

    def test_write_payload_uses_batch_update_and_cell_hyperlinks(self):
        service = Mock()
        spreadsheets = service.spreadsheets.return_value
        spreadsheets.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": ALL_CRITERIA_SHEET, "sheetId": 123}}]
        }
        spreadsheets.batchUpdate.return_value.execute.return_value = {}
        values_service = spreadsheets.values.return_value
        values_service.batchClear.return_value.execute.return_value = {}
        values_service.batchUpdate.return_value.execute.return_value = {}
        payload = [
            {
                "title": ALL_CRITERIA_SHEET,
                "values": [AI_REPORT_HEADERS, ["7A", "Math", "Teacher A", 1, "Solves", "OK", "Clear", "", "Открыть"]],
                "hyperlinks": [{"row_index": 1, "column_index": AI_REPORT_HEADERS.index("Ссылка на таблицу"), "url": "https://docs.google.com/spreadsheets/d/source/edit"}],
            }
        ]

        _write_payload(service, "spreadsheet123", payload)

        values_service.batchClear.assert_called_once()
        values_service.batchUpdate.assert_called_once()
        body = spreadsheets.batchUpdate.call_args.kwargs["body"]
        self.assertTrue(
            any(
                request.get("repeatCell", {}).get("cell", {}).get("userEnteredFormat", {}).get("textFormat", {}).get("link", {}).get("uri")
                == "https://docs.google.com/spreadsheets/d/source/edit"
                for request in body["requests"]
            )
        )


class AICriteriaReportUpdateTests(TestCase):
    def test_skips_when_no_active_target(self):
        job_run = _job_run_with_ai_rows()

        report = update_ai_criteria_google_report(job_run)

        self.assertEqual(report["status"], "not_configured")
        self.assertTrue(JobLog.objects.filter(job_run=job_run, message="Google AI report update skipped").exists())

    @patch("pipeline.ai_criteria_report._write_payload")
    @patch("pipeline.ai_criteria_report._build_sheets_service", return_value=Mock())
    @patch("pipeline.ai_criteria_report.timezone.now")
    def test_updates_active_target_with_tbilisi_timestamp(self, mocked_now, mocked_service, mocked_write):
        mocked_now.return_value = datetime(2026, 5, 6, 5, 39, 49, tzinfo=datetime_timezone.utc)
        target = AICriteriaReportTarget.objects.create(
            name="AI Report",
            google_sheet_url="https://docs.google.com/spreadsheets/d/report123/edit",
            is_active=True,
        )
        job_run = _job_run_with_ai_rows()

        report = update_ai_criteria_google_report(job_run)

        self.assertEqual(report["status"], "updated")
        self.assertEqual(report["target_id"], target.id)
        self.assertEqual(report["updated_at_display"], "6 мая 2026, 09:39:49 (Тбилиси)")
        mocked_service.assert_called_once()
        mocked_write.assert_called_once()
        self.assertTrue(JobLog.objects.filter(job_run=job_run, message="Google AI report update finished").exists())
