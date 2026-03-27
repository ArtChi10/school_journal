from django.test import TestCase
from django.urls import reverse

from pipeline.models import CriterionEntry


class CriteriaTableViewTests(TestCase):
    def setUp(self):
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