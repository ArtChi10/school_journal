from decimal import Decimal

from django.test import TestCase

from webapp.models import AssessmentCriterion, ClassWorkbook, Student, StudentAssessment, SubjectSheet


class Data101ModelsTest(TestCase):
    def test_class_4a_dataset_persists_with_relations(self) -> None:
        workbook = ClassWorkbook.objects.create(
            class_code="4A",
            source_url="https://docs.google.com/spreadsheets/d/workbook-4a",
            period="module-1",
            fetched_at="2026-03-01T08:00:00Z",
        )
        sheet = SubjectSheet.objects.create(
            workbook=workbook,
            sheet_name="Math_M1",
            subject_name="Mathematics",
            teacher_name="Alexander Belov",
            module_number=1,
            descriptor_text="Core criteria for module 1",
            is_tutor=False,
        )
        student = Student.objects.create(
            class_code="4A",
            first_name="Ivan",
            last_name="Ivanov",
            full_name_normalized="ivanov_ivan",
        )
        criterion = AssessmentCriterion.objects.create(
            subject_sheet=sheet,
            column_index=4,
            criterion_text="Solves two-step equations",
            criterion_type=AssessmentCriterion.CriterionType.CRITERION,
        )

        graded = StudentAssessment.objects.create(
            subject_sheet=sheet,
            student=student,
            criterion=criterion,
            raw_value="A",
            normalized_level="advanced",
            numeric_score=Decimal("4.00"),
            comment_text="Great progress",
            retake_flag=False,
        )
        comment_only = StudentAssessment.objects.create(
            subject_sheet=sheet,
            student=student,
            criterion=None,
            raw_value="",
            normalized_level="",
            numeric_score=None,
            comment_text="Needs to revise fractions",
            retake_flag=True,
        )

        self.assertEqual(ClassWorkbook.objects.filter(class_code="4A").count(), 1)
        self.assertEqual(SubjectSheet.objects.filter(workbook=workbook).count(), 1)
        self.assertEqual(Student.objects.filter(class_code="4A").count(), 1)
        self.assertEqual(AssessmentCriterion.objects.filter(subject_sheet=sheet).count(), 1)

        self.assertEqual(graded.criterion_id, criterion.id)
        self.assertIsNone(comment_only.criterion_id)
        self.assertEqual(StudentAssessment.objects.filter(subject_sheet=sheet, student=student).count(), 2)