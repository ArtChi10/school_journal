import uuid
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from jobs.models import JobRun


class RBACJobViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")
        self.job = JobRun.objects.create(job_type="run_validation")

    def _grant(self, codename: str):
        perm = Permission.objects.get(codename=codename)
        self.user.user_permissions.add(perm)

    def test_run_full_pipeline_forbidden_without_permission(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("run_full_pipeline"))

        self.assertEqual(response.status_code, 403)
        self.assertIn("нельзя запускать полный пайплайн", response.content.decode("utf-8"))

    @patch("jobs.views.run_full_pipeline")
    def test_run_full_pipeline_allowed_with_permission(self, mocked_runner):
        self._grant("run_full_pipeline")
        self.client.force_login(self.user)
        fake_job = JobRun(id=uuid.uuid4())
        mocked_runner.return_value = fake_job

        response = self.client.post(reverse("run_full_pipeline"))

        self.assertEqual(response.status_code, 302)
        mocked_runner.assert_called_once()

    def test_send_reminders_forbidden_without_permission(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("send_reminders", kwargs={"run_id": self.job.id}))

        self.assertEqual(response.status_code, 403)
        self.assertIn("нельзя отправлять напоминания", response.content.decode("utf-8"))

    @patch("jobs.views.run_validation_reminders_job")
    def test_send_reminders_allowed_with_permission(self, mocked_sender):
        self._grant("send_reminders")
        self.client.force_login(self.user)
        reminder_job = JobRun.objects.create(
            job_type="send_validation_reminders",
            result_json={"summary": {"sent": 1, "skipped": 0, "errors": 0}},
        )
        mocked_sender.return_value = reminder_job

        response = self.client.post(reverse("send_reminders", kwargs={"run_id": self.job.id}))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("job_run_detail", kwargs={"run_id": reminder_job.id}))
        mocked_sender.assert_called_once()

    def test_job_run_list_forbidden_without_view_permission(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("job_run_list"))

        self.assertEqual(response.status_code, 403)
        self.assertIn("нет прав на просмотр запусков", response.content.decode("utf-8"))

    def test_job_run_list_allowed_with_view_permission(self):
        self._grant("view_jobrun")
        self.client.force_login(self.user)

        response = self.client.get(reverse("job_run_list"))

        self.assertEqual(response.status_code, 200)

    def test_export_issues_forbidden_without_view_permission(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("export_run_issues_json", kwargs={"run_id": self.job.id}))

        self.assertEqual(response.status_code, 403)
        self.assertIn("нет прав на экспорт issues", response.content.decode("utf-8"))

    def test_export_issues_allowed_with_view_permission(self):
        self._grant("view_jobrun")
        self.client.force_login(self.user)

        response = self.client.get(reverse("export_run_issues_csv", kwargs={"run_id": self.job.id}))

        self.assertEqual(response.status_code, 200)