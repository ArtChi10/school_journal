from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from pipeline.models import CriterionEntry, ParentContact, ValidCriterionTemplate


class CriteriaTableViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")
        self.user.user_permissions.add(Permission.objects.get(codename="view_criterionentry"))
        self.client.force_login(self.user)
        CriterionEntry.objects.create(
            class_code="4A",
            subject_name="Math",
            teacher_name="Ms. Frizzle",
            module_number=2,
            criterion_text="Критерий 1",
            criterion_text_ai="Нормализованный критерий",
            source_sheet_name="Math",
            source_workbook="criteria.xlsx",
        )
        CriterionEntry.objects.create(
            class_code="5B",
            subject_name="History",
            teacher_name="Mr. History",
            module_number=1,
            criterion_text="Критерий 2",
            criterion_text_ai="",
            source_sheet_name="History",
            source_workbook="criteria.xlsx",
        )

    def test_filters_by_class_code(self):
        response = self.client.get(reverse("pipeline:criteria_table"), {"class_code": "4A"})

        self.assertEqual(response.status_code, 200)
        page = response.content.decode("utf-8")
        self.assertIn("Критерий 1", page)
        self.assertNotIn("Критерий 2", page)
        self.assertIn("Нормализованный критерий", page)


class ParentContactsViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="editor", password="p")
        perms = Permission.objects.filter(codename__in=["view_parentcontact", "add_parentcontact", "change_parentcontact"])
        self.user.user_permissions.add(*perms)
        self.client.force_login(self.user)

    def test_create_edit_and_disable_contact(self):
        create_response = self.client.post(
            reverse("pipeline:parent_contact_create"),
            {
                "parallel": 3,
                "class_code": "3A",
                "student_name": "Иван Иванов",
                "parent_email_1": "p1@example.com",
                "parent_email_2": "",
                "is_active": "on",
            },
        )
        self.assertEqual(create_response.status_code, 302)
        contact = ParentContact.objects.get(student_name="Иван Иванов")

        edit_response = self.client.post(
            reverse("pipeline:parent_contact_edit", args=[contact.id]),
            {
                "parallel": 3,
                "class_code": "3A",
                "student_name": "Иван Иванов",
                "parent_email_1": "updated@example.com",
                "parent_email_2": "p2@example.com",
                "is_active": "on",
            },
        )
        self.assertEqual(edit_response.status_code, 302)

        disable_response = self.client.post(reverse("pipeline:parent_contact_disable", args=[contact.id]))
        self.assertEqual(disable_response.status_code, 302)

        contact.refresh_from_db()
        self.assertEqual(contact.parent_email_1, "updated@example.com")
        self.assertFalse(contact.is_active)

    def test_import_csv_upsert_and_errors(self):
        ParentContact.objects.create(parallel=3, student_name="Иван Иванов", parent_email_1="old@example.com")

        payload = "parallel,student_name,parent_email_1,parent_email_2\n3,Иван Иванов,new@example.com,p2@example.com\n3,Петр Петров,bad-email,\n4,Мария Сидорова,m@example.com,\n"
        response = self.client.post(
            reverse("pipeline:parent_contacts_import"),
            {"file": self._uploaded_csv(payload)},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        existing = ParentContact.objects.get(parallel=3, student_name="Иван Иванов")
        self.assertEqual(existing.parent_email_1, "new@example.com")
        self.assertTrue(ParentContact.objects.filter(parallel=4, student_name="Мария Сидорова").exists())
        self.assertContains(response, "created=1")
        self.assertContains(response, "updated=1")
        self.assertContains(response, "errors=1")

    @staticmethod
    def _uploaded_csv(content: str):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile("parents.csv", content.encode("utf-8"), content_type="text/csv")

class ValidCriteriaViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="admin", password="p")
        perms = Permission.objects.filter(
            codename__in=["view_validcriteriontemplate", "add_validcriteriontemplate", "change_validcriteriontemplate"]
        )
        self.user.user_permissions.add(*perms)
        self.client.force_login(self.user)

    def test_create_edit_and_disable_template(self):
        create_response = self.client.post(
            reverse("pipeline:valid_criterion_create"),
            {"name": "Итоговая работа", "is_active": "on"},
        )
        self.assertEqual(create_response.status_code, 302)
        template = ValidCriterionTemplate.objects.get(name="Итоговая работа")
        self.assertEqual(template.normalized_name, "итоговая работа")
        self.assertEqual(template.created_by, self.user)

        edit_response = self.client.post(
            reverse("pipeline:valid_criterion_edit", args=[template.id]),
            {"name": "  Итоговая   работа  ", "is_active": "on"},
        )
        self.assertEqual(edit_response.status_code, 302)

        disable_response = self.client.post(reverse("pipeline:valid_criterion_disable", args=[template.id]))
        self.assertEqual(disable_response.status_code, 302)

        template.refresh_from_db()
        self.assertEqual(template.normalized_name, "итоговая работа")
        self.assertFalse(template.is_active)