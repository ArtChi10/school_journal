import uuid

from django.db import models


class JobRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_type = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    params_json = models.JSONField(default=dict, blank=True)
    result_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.job_type} ({self.status})"


class JobLog(models.Model):
    class Level(models.TextChoices):
        DEBUG = "debug", "Debug"
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    job_run = models.ForeignKey(JobRun, on_delete=models.CASCADE, related_name="logs")
    ts = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=20, choices=Level.choices, default=Level.INFO)
    message = models.TextField()
    context_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["ts"]

    def __str__(self) -> str:
        return f"{self.ts} [{self.level}] {self.message[:50]}"