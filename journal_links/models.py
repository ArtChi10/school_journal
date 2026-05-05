from django.db import models


class ClassSheetLink(models.Model):
    class_code = models.CharField(max_length=64)
    subject_name = models.CharField(max_length=255, blank=True, default="")
    teacher_name = models.CharField(max_length=255, blank=True, default="")
    google_sheet_url = models.URLField(max_length=500)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["class_code", "subject_name"],
                name="uq_classsheetlink_class_subject",
            )
        ]
        ordering = ["class_code", "subject_name"]

    def __str__(self) -> str:
        return f"{self.class_code} — {self.subject_name}"


class DescriptorCriteriaReportTarget(models.Model):
    name = models.CharField(max_length=255, default="Descriptor criteria report")
    google_sheet_url = models.URLField(max_length=500)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active", "-updated_at", "name"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_active:
            DescriptorCriteriaReportTarget.objects.exclude(pk=self.pk).update(is_active=False)

    def __str__(self) -> str:
        return self.name
