from django.db import models

class TeacherContact(models.Model):
    name = models.CharField(max_length=255, unique=True)
    chat_id = models.CharField(max_length=64, blank=True, default="")
    is_active = models.BooleanField(default=True)
    registration_token = models.CharField(max_length=64, unique=True, null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.chat_id or 'unlinked'})"