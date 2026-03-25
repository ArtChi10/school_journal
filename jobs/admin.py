from django.contrib import admin

from .models import JobLog, JobRun


@admin.register(JobRun)
class JobRunAdmin(admin.ModelAdmin):
    list_display = ("id", "job_type", "status", "started_at", "finished_at")
    list_filter = ("status", "job_type")
    search_fields = ("id", "job_type")


@admin.register(JobLog)
class JobLogAdmin(admin.ModelAdmin):
    list_display = ("job_run", "ts", "level", "message")
    list_filter = ("level", "ts")
    search_fields = ("message", "job_run__job_type")