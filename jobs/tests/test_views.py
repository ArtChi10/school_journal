import uuid
from unittest.mock import patch
from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from jobs.models import JobLog, JobRun
from notifications.models import TeacherConfirmation


class JobRunDetailViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="vp", password="p")
        self.user.user_permissions.add(Permission.objects.get(codename="view_jobrun"))
        self.client.force_login(self.user)
    def test_detail_shows_teacher_confirmations(self):
        job_run = JobRun.objects.create(job_type="run_validation")
        TeacherConfirmation.objects.create(
            job_run=job_run,
            teacher_name="Teacher A",
            chat_id="100",
            message_text="исправил",
            confirmed_at="2026-03-28T10:00:00Z",
        )

        response = self.client.get(reverse("job_run_detail", kwargs={"run_id": job_run.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Подтверждения учителей")
        self.assertContains(response, "Teacher A")
        self.assertContains(response, "исправил")
        self.assertContains(response, "Export JSON")
        self.assertContains(response, "Export CSV")

    def test_detail_shows_pipeline_sections(self):
        job_run = JobRun.objects.create(
            job_type="run_full_pipeline",
            status=JobRun.Status.PARTIAL,
            result_json={
                "summary": {"steps_total": 5},
                "pipeline_steps": [{"key": "TASK-021", "title": "Download descriptors", "status": "partial"}],
                "artifacts": {"xlsx_files": ["/tmp/a.xlsx"]},
                "errors": [{"step": "TASK-021", "reason": "403 unauthorized"}],
            },
        )
        JobLog.objects.create(
            job_run=job_run,
            level=JobLog.Level.ERROR,
            message="step_failed",
            context_json={"step": "TASK-021", "reason": "403 unauthorized"},
        )
        response = self.client.get(reverse("job_run_detail", kwargs={"run_id": job_run.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pipeline steps")
        self.assertContains(response, "Started at")
        self.assertContains(response, "Finished at")
        self.assertContains(response, "Проблемный шаг")
        self.assertContains(response, "#step-task-021")
        self.assertContains(response, "403 unauthorized")


class RunFullPipelineViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="admin", password="p")
        for codename in ("view_jobrun", "run_full_pipeline"):
            self.user.user_permissions.add(Permission.objects.get(codename=codename))
        self.client.force_login(self.user)
    @patch("jobs.views.run_full_pipeline")
    def test_post_runs_pipeline_and_redirects_to_detail(self, mocked_runner):
        fake_job = JobRun(id=uuid.uuid4())
        mocked_runner.return_value = fake_job

        response = self.client.post(reverse("run_full_pipeline"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("job_run_detail", kwargs={"run_id": fake_job.id}))
        mocked_runner.assert_called_once()

    def test_list_contains_full_pipeline_button(self):
        JobRun.objects.create(job_type="run_validation", status=JobRun.Status.PENDING)
        response = self.client.get(reverse("job_run_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Запустить полный пайплайн")
        self.assertContains(response, "status-queued")
        self.assertContains(response, "queued")

class JobRunIssuesExportViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="exporter", password="p")
        self.user.user_permissions.add(Permission.objects.get(codename="view_jobrun"))
        self.client.force_login(self.user)

    def test_export_json_returns_issues_payload(self):
        job_run = JobRun.objects.create(
            job_type="run_validation",
            result_json={
                "issues": [
                    {"sheet": "Лист 1", "teacher_name": "Иванов И.И.", "severity": "warning", "message": "Проверьте значение"}
                ]
            },
        )

        response = self.client.get(reverse("export_run_issues_json", kwargs={"run_id": job_run.id}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json; charset=utf-8")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn("Лист 1", response.content.decode("utf-8"))

    def test_export_csv_returns_bom_and_headers(self):
        job_run = JobRun.objects.create(
            job_type="run_validation",
            result_json={
                "issues": [
                    {
                        "sheet": "Лист 1",
                        "class_code": "7A",
                        "subject_name": "Математика",
                        "teacher_name": "Петров П.П.",
                        "student": "Сидоров",
                        "row": 12,
                        "field": "mark",
                        "code": "invalid_mark",
                        "severity": "critical",
                        "message": "Оценка вне диапазона",
                    }
                ]
            },
        )

        response = self.client.get(reverse("export_run_issues_csv", kwargs={"run_id": job_run.id}))
        payload = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"))
        text = payload.decode("utf-8")
        self.assertIn("sheet,class_code,subject_name,teacher_name,student,row,field,code,severity,message", text)
        self.assertIn("Математика", text)

    def test_export_csv_returns_headers_for_empty_issues(self):
        job_run = JobRun.objects.create(job_type="run_validation", result_json={"issues": []})

        response = self.client.get(reverse("export_run_issues_csv", kwargs={"run_id": job_run.id}))
        payload = b"".join(response.streaming_content).decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("sheet,class_code,subject_name,teacher_name,student,row,field,code,severity,message", payload)