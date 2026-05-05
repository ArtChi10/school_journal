from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from jobs.models import JobLog, JobRun
from journal_links.models import DescriptorCriteriaReportTarget
from validation.descriptor_criteria_report import (
    ALL_SUBJECTS_SHEET,
    ALL_SUBJECTS_HEADERS,
    COLOR_GRAY,
    COLOR_GREEN,
    COLOR_RED,
    COLOR_YELLOW,
    PROBLEMS_SHEET,
    SUMMARY_SHEET,
    build_descriptor_criteria_report_payload,
    extract_spreadsheet_id,
    update_descriptor_criteria_google_report,
    _format_requests_for_values,
    _write_payload,
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
                    "grades_ratio": "6/6",
                    "grades_status": "ok",
                    "grades_filled": 6,
                    "grades_total": 6,
                    "grades_missing": 0,
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
                    "grades_ratio": "4/6",
                    "grades_status": "missing",
                    "grades_filled": 4,
                    "grades_total": 6,
                    "grades_missing": 2,
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
        self.assertEqual(problems["values"][0], ALL_SUBJECTS_HEADERS)
        self.assertIn("Оценки", problems["values"][0])
        self.assertNotIn("grades_ratio", problems["values"][0])
        self.assertNotIn("criteria_total", problems["values"][0])
        self.assertNotIn("grades_total", problems["values"][0])
        self.assertIn("Science", problems["values"][1])
        self.assertIn("Не заполнены", problems["values"][1])
        self.assertNotIn("4/6", problems["values"][1])


class DescriptorCriteriaReportFormattingTests(TestCase):
    def _subject_row(self, **overrides):
        row = {
            "Класс": "7A",
            "Предмет": "Math",
            "Учитель": "Teacher A",
            "Модуль": 1,
            "Дескриптор": "Заполнен",
            "Критерии": "Заполнены",
            "Оценки": "Заполнены",
            "Статус": "OK",
            "Ссылка на таблицу": "https://docs.google.com/spreadsheets/d/source/edit",
        }
        row.update(overrides)
        return [row.get(header, "") for header in ALL_SUBJECTS_HEADERS]

    def _cell_colors(self, requests):
        colors = {}
        for request in requests:
            repeat_cell = request.get("repeatCell")
            if not repeat_cell:
                continue
            request_range = repeat_cell["range"]
            if request_range["endRowIndex"] - request_range["startRowIndex"] != 1:
                continue
            if request_range["endColumnIndex"] - request_range["startColumnIndex"] != 1:
                continue
            color = repeat_cell["cell"]["userEnteredFormat"].get("backgroundColor")
            colors[(request_range["startRowIndex"], request_range["startColumnIndex"])] = color
        return colors

    def test_builds_status_and_header_format_requests(self):
        values = [
            ALL_SUBJECTS_HEADERS,
            self._subject_row(),
            self._subject_row(
                Дескриптор="Не заполнен",
                Критерии="Не заполнены",
                Оценки="Не заполнены",
                Статус="Есть проблемы",
            ),
            self._subject_row(Оценки="Не применимо"),
        ]

        requests = _format_requests_for_values(123, values)
        colors = self._cell_colors(requests)
        header_requests = [
            request
            for request in requests
            if request.get("repeatCell", {}).get("range", {}).get("startRowIndex") == 0
            and request.get("repeatCell", {}).get("range", {}).get("endRowIndex") == 1
        ]

        self.assertTrue(any("updateSheetProperties" in request for request in requests))
        self.assertTrue(any("autoResizeDimensions" in request for request in requests))
        self.assertTrue(any(request["repeatCell"]["cell"]["userEnteredFormat"]["textFormat"]["bold"] is True for request in header_requests))
        self.assertIn(COLOR_GREEN, [request["repeatCell"]["cell"]["userEnteredFormat"]["backgroundColor"] for request in requests if "repeatCell" in request])
        self.assertEqual(colors[(1, ALL_SUBJECTS_HEADERS.index("Дескриптор"))], COLOR_GREEN)
        self.assertEqual(colors[(2, ALL_SUBJECTS_HEADERS.index("Статус"))], COLOR_RED)
        self.assertEqual(colors[(2, ALL_SUBJECTS_HEADERS.index("Оценки"))], COLOR_YELLOW)
        self.assertEqual(colors[(2, ALL_SUBJECTS_HEADERS.index("Критерии"))], COLOR_YELLOW)
        self.assertEqual(colors[(3, ALL_SUBJECTS_HEADERS.index("Оценки"))], COLOR_GRAY)

    def test_write_payload_applies_formatting_after_values(self):
        service = Mock()
        spreadsheets = service.spreadsheets.return_value
        spreadsheets.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": ALL_SUBJECTS_SHEET, "sheetId": 123}}]
        }
        spreadsheets.batchUpdate.return_value.execute.return_value = {}
        values_service = spreadsheets.values.return_value
        values_service.batchClear.return_value.execute.return_value = {}
        values_service.batchUpdate.return_value.execute.return_value = {}
        payload = [{"title": ALL_SUBJECTS_SHEET, "values": [ALL_SUBJECTS_HEADERS, self._subject_row(overall_status="problem")]}]

        _write_payload(service, "spreadsheet123", payload)

        values_service.batchClear.assert_called_once()
        values_service.batchUpdate.assert_called_once()
        values_service.clear.assert_not_called()
        values_service.update.assert_not_called()
        self.assertEqual(values_service.batchClear.call_args.kwargs["body"]["ranges"], ["'All subjects'!A:Z"])
        self.assertEqual(values_service.batchUpdate.call_args.kwargs["body"]["data"][0]["range"], "'All subjects'!A1")
        spreadsheets.batchUpdate.assert_called_once()
        body = spreadsheets.batchUpdate.call_args.kwargs["body"]
        self.assertTrue(body["requests"])


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
