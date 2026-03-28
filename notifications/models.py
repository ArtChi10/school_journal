from django.db import models

class TeacherContact(models.Model):
    name = models.CharField(max_length=255, unique=True)
    chat_id = models.CharField(max_length=64, blank=True, default="")
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    registration_token = models.CharField(max_length=64, unique=True, null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.chat_id or 'unlinked'})"

    @property
    def teacher_name(self) -> str:
        """Backward-compatible alias used by older admin list_display configs."""
        return self.name


class TeacherConfirmation(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"

    job_run = models.ForeignKey(
        "jobs.JobRun",
        on_delete=models.CASCADE,
        related_name="teacher_confirmations",
    )
    teacher_name = models.CharField(max_length=255)
    chat_id = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CONFIRMED)
    message_text = models.TextField()
    confirmed_at = models.DateTimeField()

    class Meta:
        ordering = ["-confirmed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job_run", "chat_id"],
                name="uniq_teacher_confirmation_per_job_chat",
            )
        ]

    def __str__(self) -> str:
        return f"{self.teacher_name} -> {self.job_run_id} ({self.status})"