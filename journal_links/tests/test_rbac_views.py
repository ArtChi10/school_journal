from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from jobs.models import JobRun
from journal_links.models import ClassSheetLink


class JournalLinksRBACViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")
        self.link = ClassSheetLink.objects.create(
            class_code="7B",
            subject_name="Science",
            teacher_name="Teacher",
            google_sheet_url="https://docs.google.com/spreadsheets/d/abc123/edit#gid=0",
            is_active=True,
        )

    def _grant(self, codename: str):
        perm = Permission.objects.get(codename=codename)
        self.user.user_permissions.add(perm)

    def test_validation_forbidden_without_permission(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("journal_links:run_link_validation", args=[self.link.id]))

        self.assertEqual(response.status_code, 403)
        self.assertIn("нельзя запускать валидацию", response.content.decode("utf-8"))

    def test_validation_allowed_with_permission(self):
        self._grant("run_validation")
        self.client.force_login(self.user)
        fake_job = JobRun(id=uuid4())
        with patch("journal_links.views.run_validation_job", return_value=fake_job) as mocked:
            response = self.client.post(reverse("journal_links:run_link_validation", args=[self.link.id]))

        self.assertEqual(response.status_code, 302)
        mocked.assert_called_once_with(link_id=self.link.id, initiated_by=self.user)

    def test_edit_forbidden_without_change_permission(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("journal_links:edit_link", args=[self.link.id]))

        self.assertEqual(response.status_code, 403)
        self.assertIn("нельзя изменять ссылки классов", response.content.decode("utf-8"))

    def test_list_forbidden_without_view_permission(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("journal_links:list_links"))

        self.assertEqual(response.status_code, 403)

    def test_list_allowed_with_view_permission(self):
        self._grant("view_classsheetlink")
        self.client.force_login(self.user)

        response = self.client.get(reverse("journal_links:list_links"))

        self.assertEqual(response.status_code, 200)