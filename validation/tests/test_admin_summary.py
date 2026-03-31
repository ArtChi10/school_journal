from django.test import TestCase

from jobs.models import JobRun
from validation.admin_summary import build_missing_data_summary


class AdminSummaryTests(TestCase):
    def test_builds_grouped_summary_and_text(self):
        job = JobRun.objects.create(
            job_type="check_missing_data",
            result_json={
                "issues": [
                    {"teacher_name": "Иванова А.", "class_code": "4A", "subject_name": "Математика", "code": "CRITERIA_HEADERS_EMPTY", "issue_group": "criteria", "missing_count": 3},
                    {"teacher_name": "Иванова А.", "class_code": "4A", "subject_name": "Математика", "code": "GRADE_EMPTY", "issue_group": "grades", "missing_count": 14},
                    {"teacher_name": "Петров Б.", "class_code": "5B", "subject_name": "Русский", "code": "DESCRIPTOR_EMPTY", "issue_group": "descriptor", "missing_count": 1},
                ]
            },
        )

        summary = build_missing_data_summary(job)

        self.assertEqual(summary["teachers_total"], 2)
        self.assertEqual(summary["subjects_total"], 2)
        self.assertEqual(summary["criteria_missing_total"], 3)
        self.assertEqual(summary["grades_missing_total"], 14)
        self.assertEqual(summary["descriptor_missing_total"], 1)
        self.assertIn("Иванова А.", summary["text"])
        self.assertIn("4A / Математика", summary["text"])

    def test_empty_summary_returns_all_filled_message(self):
        job = JobRun.objects.create(job_type="check_missing_data", result_json={"issues": []})
        summary = build_missing_data_summary(job)
        self.assertEqual(summary["teachers_total"], 0)
        self.assertIn("Всё заполнено", summary["text"])