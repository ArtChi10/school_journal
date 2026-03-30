from django.db import models


class ClassWorkbook(models.Model):
    class_code = models.CharField(max_length=32)
    source_url = models.URLField(max_length=500)
    period = models.CharField(max_length=64)
    fetched_at = models.DateTimeField()

    class Meta:
        ordering = ["class_code", "period", "-fetched_at"]
        indexes = [
            models.Index(fields=["class_code"]),
            models.Index(fields=["fetched_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.class_code} / {self.period}"


class SubjectSheet(models.Model):
    workbook = models.ForeignKey(ClassWorkbook, on_delete=models.CASCADE, related_name="subject_sheets")
    sheet_name = models.CharField(max_length=255)
    subject_name = models.CharField(max_length=255)
    teacher_name = models.CharField(max_length=255, blank=True, default="")
    module_number = models.PositiveIntegerField()
    descriptor_text = models.TextField(blank=True, default="")
    is_tutor = models.BooleanField(default=False)

    class Meta:
        ordering = ["workbook", "module_number", "subject_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["workbook", "sheet_name"],
                name="uq_subjectsheet_workbook_sheet_name",
            )
        ]
        indexes = [
            models.Index(fields=["subject_name"]),
            models.Index(fields=["module_number"]),
        ]

    def __str__(self) -> str:
        return f"{self.subject_name} ({self.sheet_name})"


class Student(models.Model):
    class_code = models.CharField(max_length=32)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    full_name_normalized = models.CharField(max_length=511)

    class Meta:
        ordering = ["class_code", "last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["class_code", "full_name_normalized"],
                name="uq_student_class_full_name_normalized",
            )
        ]
        indexes = [
            models.Index(fields=["class_code"]),
            models.Index(fields=["full_name_normalized"]),
        ]

    def __str__(self) -> str:
        return f"{self.last_name} {self.first_name}"


class AssessmentCriterion(models.Model):
    class CriterionType(models.TextChoices):
        CRITERION = "criterion", "criterion"
        COMMENT = "comment", "comment"
        RETAKE = "retake", "retake"
        TEST = "test", "test"

    subject_sheet = models.ForeignKey(SubjectSheet, on_delete=models.CASCADE, related_name="criteria")
    column_index = models.PositiveIntegerField()
    criterion_text = models.TextField()
    criterion_type = models.CharField(max_length=16, choices=CriterionType.choices)

    class Meta:
        ordering = ["subject_sheet", "column_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["subject_sheet", "column_index"],
                name="uq_assessmentcriterion_sheet_col",
            )
        ]

    def __str__(self) -> str:
        return f"{self.subject_sheet_id}:{self.column_index}:{self.criterion_type}"


class StudentAssessment(models.Model):
    subject_sheet = models.ForeignKey(SubjectSheet, on_delete=models.CASCADE, related_name="student_assessments")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="assessments")
    criterion = models.ForeignKey(
        AssessmentCriterion,
        on_delete=models.SET_NULL,
        related_name="student_assessments",
        null=True,
        blank=True,
    )
    raw_value = models.CharField(max_length=255, blank=True, default="")
    normalized_level = models.CharField(max_length=64, blank=True, default="")
    numeric_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    comment_text = models.TextField(blank=True, default="")
    retake_flag = models.BooleanField(default=False)

    class Meta:
        ordering = ["subject_sheet", "student", "id"]
        indexes = [
            models.Index(fields=["subject_sheet", "student"]),
            models.Index(fields=["criterion"]),
            models.Index(fields=["retake_flag"]),
        ]

    def __str__(self) -> str:
        return f"{self.student_id} @ {self.subject_sheet_id}"