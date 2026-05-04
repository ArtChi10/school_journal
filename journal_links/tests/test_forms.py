from django.test import TestCase

from journal_links.forms import ClassSheetLinkForm
from journal_links.models import ClassSheetLink


class ClassSheetLinkFormTests(TestCase):
    def test_exposes_only_class_url_and_active_fields(self):
        form = ClassSheetLinkForm()

        self.assertEqual(list(form.fields.keys()), ["class_code", "google_sheet_url", "is_active"])
    def test_accepts_google_sheets_url(self):
        form = ClassSheetLinkForm(
            data={
                "class_code": "5A",
                "google_sheet_url": "https://docs.google.com/spreadsheets/d/abc123/edit#gid=0",
                "is_active": True,
            }
        )

        self.assertTrue(form.is_valid())

    def test_rejects_drive_url(self):
        form = ClassSheetLinkForm(
            data={
                "class_code": "5A",
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
                "google_sheet_url": "https://docs.google.com/spreadsheets/d/",
                "is_active": True,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("google_sheet_url", form.errors)

    def test_leaves_subject_and_teacher_empty_on_save(self):
        form = ClassSheetLinkForm(
            data={
                "class_code": "11A",
                "google_sheet_url": "https://docs.google.com/spreadsheets/d/abc123/edit#gid=0",
                "is_active": True,
            }
        )

        self.assertTrue(form.is_valid())
        link = form.save()
        self.assertEqual(link.subject_name, "")
        self.assertEqual(link.teacher_name, "")

    def test_rejects_second_active_link_for_same_class(self):
        ClassSheetLink.objects.create(
            class_code="5A",
            google_sheet_url="https://docs.google.com/spreadsheets/d/existing/edit",
            is_active=True,
        )

        form = ClassSheetLinkForm(
            data={
                "class_code": "5A",
                "google_sheet_url": "https://docs.google.com/spreadsheets/d/newlink/edit",
                "is_active": True,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("уже есть активная ссылка", form.non_field_errors()[0])

    def test_allows_new_active_link_when_old_one_is_inactive(self):
        ClassSheetLink.objects.create(
            class_code="5A",
            google_sheet_url="https://docs.google.com/spreadsheets/d/existing/edit",
            is_active=False,
        )

        form = ClassSheetLinkForm(
            data={
                "class_code": "5A",
                "google_sheet_url": "https://docs.google.com/spreadsheets/d/newlink/edit",
                "is_active": True,
            }
        )

        self.assertTrue(form.is_valid())
