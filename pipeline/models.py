import re

from django.conf import settings
from django.core.validators import EmailValidator
from django.db import models
def normalize_criterion_name(value: str) -> str:
    text = str(value or "").replace("\xa0", " ").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text

class CriterionEntry(models.Model):
    class ValidationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        VALID = "valid", "Valid"
        INVALID = "invalid", "Invalid"
        OVERRIDE = "override", "Override"
        OVERRIDDEN_VALID = "overridden_valid", "Overridden valid"
        RECHECK = "recheck", "Recheck"
    class_code = models.CharField(max_length=64)
    subject_name = models.CharField(max_length=255)
    teacher_name = models.CharField(max_length=255)
    module_number = models.PositiveIntegerField()
    criterion_text = models.TextField()
    criterion_text_ai = models.TextField(blank=True, default="")
    validation_status = models.CharField(
        max_length=16,
        choices=ValidationStatus.choices,
        default=ValidationStatus.PENDING,
    )
    ai_verdict = models.CharField(max_length=32, blank=True, default="")
    ai_why = models.TextField(blank=True, default="")
    ai_fix_suggestion = models.TextField(blank=True, default="")
    ai_variants_json = models.JSONField(blank=True, default=list)
    needs_recheck = models.BooleanField(default=False)
    last_checked_at = models.DateTimeField(null=True, blank=True)
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
            models.Index(fields=["validation_status"]),
        ]
        ordering = ["class_code", "subject_name", "module_number", "criterion_text"]

    def __str__(self) -> str:
        return f"{self.class_code} / {self.subject_name} / M{self.module_number}"


class CriterionReviewEvent(models.Model):
    class EventType(models.TextChoices):
        AI_VERDICT = "ai_verdict", "AI verdict"
        NOTIFICATION_SENT = "notification_sent", "Notification sent"
        TEACHER_CONFIRMED = "teacher_confirmed", "Teacher confirmed"
        RECHECK = "recheck", "Recheck"
        OVERRIDDEN_VALID = "overridden_valid", "Overridden valid"

    criterion = models.ForeignKey(
        CriterionEntry,
        on_delete=models.CASCADE,
        related_name="review_events",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    actor_name = models.CharField(max_length=255, blank=True, default="")
    actor_role = models.CharField(max_length=64, blank=True, default="")
    reason = models.TextField(blank=True, default="")
    payload_json = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["criterion", "created_at"]),
            models.Index(fields=["event_type", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.criterion_id}::{self.event_type}@{self.created_at.isoformat()}"


class ValidCriterionTemplate(models.Model):
    name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="valid_criterion_templates",
    )

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["normalized_name"]),
            models.Index(fields=["is_active"]),
        ]

    def save(self, *args, **kwargs):
        self.normalized_name = normalize_criterion_name(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name

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