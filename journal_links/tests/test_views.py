from unittest.mock import patch
from uuid import uuid4
from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from jobs.models import JobRun
from journal_links.models import ClassSheetLink


class JournalLinkViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")
        self.user.user_permissions.add(Permission.objects.get(codename="run_validation"))
        self.client.force_login(self.user)
        self.link = ClassSheetLink.objects.create(
            class_code="7B",
            subject_name="Science",
            teacher_name="Teacher",
            google_sheet_url="https://docs.google.com/spreadsheets/d/abc123/edit#gid=0",
            is_active=True,
        )

    def test_run_link_validation_redirects_to_job_run_detail(self):
        fake_job = JobRun(id=uuid4())
        with patch("journal_links.views.run_validation_job", return_value=fake_job) as mocked:
            response = self.client.post(reverse("journal_links:run_link_validation", args=[self.link.id]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("job_run_detail", kwargs={"run_id": fake_job.id}))
        mocked.assert_called_once_with(link_id=self.link.id, initiated_by=self.user)