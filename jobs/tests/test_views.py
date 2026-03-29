import uuid
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse

from jobs.models import JobRun
from notifications.models import TeacherConfirmation


class JobRunDetailViewTests(TestCase):
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

    def test_detail_shows_pipeline_sections(self):
        job_run = JobRun.objects.create(
            job_type="run_full_pipeline",
            result_json={
                "summary": {"steps_total": 5},
                "pipeline_steps": [{"key": "TASK-021", "title": "Download descriptors", "status": "success"}],
                "artifacts": {"xlsx_files": ["/tmp/a.xlsx"]},
                "errors": [{"step": "TASK-025", "reason": "No contacts"}],
            },
        )

        response = self.client.get(reverse("job_run_detail", kwargs={"run_id": job_run.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pipeline steps")
        self.assertContains(response, "Artifacts")
        self.assertContains(response, "Errors")


class RunFullPipelineViewTests(TestCase):
    @patch("jobs.views.run_full_pipeline")
    def test_post_runs_pipeline_and_redirects_to_detail(self, mocked_runner):
        fake_job = JobRun(id=uuid.uuid4())
        mocked_runner.return_value = fake_job

        response = self.client.post(reverse("run_full_pipeline"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("job_run_detail", kwargs={"run_id": fake_job.id}))
        mocked_runner.assert_called_once()

    def test_list_contains_full_pipeline_button(self):
        response = self.client.get(reverse("job_run_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Запустить полный пайплайн")