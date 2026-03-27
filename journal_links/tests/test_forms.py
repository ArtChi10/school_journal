from django.test import TestCase

from journal_links.forms import ClassSheetLinkForm


class ClassSheetLinkFormTests(TestCase):
    def test_accepts_google_sheets_url(self):
        form = ClassSheetLinkForm(
            data={
                "class_code": "5A",
                "subject_name": "Math",
                "teacher_name": "Teacher",
                "google_sheet_url": "https://docs.google.com/spreadsheets/d/abc123/edit#gid=0",
                "is_active": True,
            }
        )

        self.assertTrue(form.is_valid())

    def test_rejects_drive_url(self):
        form = ClassSheetLinkForm(
            data={
                "class_code": "5A",
                "subject_name": "Math",
                "teacher_name": "Teacher",
                "google_sheet_url": "https://drive.google.com/file/d/abc123",
                "is_active": True,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("google_sheet_url", form.errors)

    def test_rejects_non_url_value(self):
        form = ClassSheetLinkForm(
            data={
                "class_code": "5A",
                "subject_name": "Math",
                "teacher_name": "Teacher",
                "google_sheet_url": "not-a-url",
                "is_active": True,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("google_sheet_url", form.errors)

    def test_rejects_google_docs_without_sheet_id(self):
        form = ClassSheetLinkForm(
            data={
                "class_code": "5A",
                "subject_name": "Math",
                "teacher_name": "Teacher",
                "google_sheet_url": "https://docs.google.com/spreadsheets/d/",
                "is_active": True,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("google_sheet_url", form.errors)