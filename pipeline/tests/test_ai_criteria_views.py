from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from jobs.models import JobRun
from journal_links.models import ClassSheetLink
from pipeline.ai_criteria_review import JOB_TYPE
from pipeline.models import AICriteriaReportTarget


class AICriteriaReviewViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="reviewer", password="p")
        perms = Permission.objects.filter(codename__in=["view_criterionentry", "run_full_pipeline", "change_criterionentry"])
        self.user.user_permissions.add(*perms)
        self.client.force_login(self.user)
        ClassSheetLink.objects.create(
            class_code="7A",
            google_sheet_url="https://docs.google.com/spreadsheets/d/source/edit",
            is_active=True,
        )

    def test_launch_page_renders(self):
        response = self.client.get(reverse("pipeline:ai_criteria_review"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI-вычитка критериев")
        self.assertContains(response, "Запустить AI-вычитку")
        self.assertContains(response, "7A")

    def test_post_launches_ai_review_for_selected_class(self):
        fake_job = JobRun(id=uuid4(), job_type=JOB_TYPE)
        with patch("pipeline.views.enqueue_ai_criteria_class_review_job", return_value=fake_job) as mocked:
            response = self.client.post(reverse("pipeline:ai_criteria_review"), {"class_code": "7A"})

        self.assertEqual(response.status_code, 302)
        self.assertIn(str(fake_job.id), response.url)
        mocked.assert_called_once_with(class_code="7A", all_active=False, initiated_by=self.user)

    def test_latest_result_table_renders(self):
        job_run = JobRun.objects.create(
            job_type=JOB_TYPE,
            result_json={
                "summary": {"classes_checked": 1, "criteria_sent_to_ai": 1, "criteria_ok": 1, "criteria_problem": 0},
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
                    }
                ],
            },
        )

        response = self.client.get(reverse("pipeline:ai_criteria_review"), {"run_id": job_run.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Solves equations")
        self.assertContains(response, "Оценка AI")
        self.assertContains(response, "Clear")

    def test_report_target_form_saves_active_target(self):
        response = self.client.post(
            reverse("pipeline:ai_criteria_report_target"),
            {
                "name": "AI Report",
                "google_sheet_url": "https://docs.google.com/spreadsheets/d/report123/edit",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        target = AICriteriaReportTarget.objects.get()
        self.assertEqual(target.name, "AI Report")
        self.assertTrue(target.is_active)
