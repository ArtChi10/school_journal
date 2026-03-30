from django.core.validators import EmailValidator
from django.db import models


class CriterionEntry(models.Model):
    class_code = models.CharField(max_length=64)
    subject_name = models.CharField(max_length=255)
    teacher_name = models.CharField(max_length=255)
    module_number = models.PositiveIntegerField()
    criterion_text = models.TextField()
    criterion_text_ai = models.TextField(blank=True, default="")
    source_sheet_name = models.CharField(max_length=255)
    source_workbook = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["class_code", "subject_name", "module_number", "criterion_text"],
                name="uq_criterionentry_class_subject_module_criterion",
            )
        ]
        indexes = [
            models.Index(fields=["class_code", "subject_name"]),
            models.Index(fields=["module_number"]),
        ]
        ordering = ["class_code", "subject_name", "module_number", "criterion_text"]

    def __str__(self) -> str:
        return f"{self.class_code} / {self.subject_name} / M{self.module_number}"

class ParentContact(models.Model):
    parallel = models.PositiveIntegerField()
    class_code = models.CharField(max_length=16, blank=True, default="")
    student_name = models.CharField(max_length=255)
    parent_email_1 = models.EmailField(max_length=255, blank=True, default="", validators=[EmailValidator()])
    parent_email_2 = models.EmailField(max_length=255, blank=True, default="", validators=[EmailValidator()])
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["parallel", "student_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["parallel", "student_name"],
                name="uq_parent_contact_parallel_student_name",
            )
        ]
        indexes = [
            models.Index(fields=["parallel"]),
            models.Index(fields=["student_name"]),
            models.Index(fields=["parent_email_1"]),
            models.Index(fields=["parent_email_2"]),
        ]

    def __str__(self) -> str:
        return f"{self.parallel}: {self.student_name}"