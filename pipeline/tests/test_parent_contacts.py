from django.test import TestCase

from pipeline.models import ParentContact
from pipeline.parent_contacts import import_parent_contacts_csv, parent_contacts_to_pipeline_payload


class ParentContactsHelpersTests(TestCase):
    def test_import_without_header(self):
        result = import_parent_contacts_csv("3,Иван Иванов,p1@example.com,p2@example.com\n".encode("utf-8"))

        self.assertEqual(result.created, 1)
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.errors, [])

    def test_payload_contains_active_contacts_only(self):
        ParentContact.objects.create(
            parallel=3,
            class_code="3A",
            student_name="Иван Иванов",
            parent_email_1="p1@example.com",
            parent_email_2="",
            is_active=True,
        )
        ParentContact.objects.create(
            parallel=3,
            class_code="3A",
            student_name="Петр Петров",
            parent_email_1="p2@example.com",
            parent_email_2="",
            is_active=False,
        )

        payload = parent_contacts_to_pipeline_payload()

        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["student"], "Иван Иванов")
        self.assertEqual(payload[0]["recipients"][0]["value"], "p1@example.com")