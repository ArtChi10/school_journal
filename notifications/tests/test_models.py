from django.test import TestCase

from notifications.models import TeacherContact


class TeacherContactCompatibilityTests(TestCase):
    def test_teacher_name_alias_returns_name(self):
        contact = TeacherContact.objects.create(name="Иван Иванов")

        self.assertEqual(contact.teacher_name, "Иван Иванов")

    def test_last_seen_at_compatibility_property_exists(self):
        contact = TeacherContact.objects.create(name="Мария Петрова")

        self.assertIsNone(contact.last_seen_at)