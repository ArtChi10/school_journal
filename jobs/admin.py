from django.contrib import admin, messages
from django.utils import timezone

from validation.services import validate_workbook
from .models import JobLog, JobRun
from .services import log_step
from notifications.reminders import send_validation_reminders_for_job



@admin.register(JobRun)
class JobRunAdmin(admin.ModelAdmin):
    list_display = ("id", "job_type", "status", "started_at", "finished_at")
    list_filter = ("status", "job_type")
    search_fields = ("id", "job_type")
    actions = ("run_validation_action", "send_telegram_reminders_action")

    @admin.action(description="Run validation for selected jobs")
    def run_validation_action(self, request, queryset):
        processed = 0
        failed = 0

        for job in queryset:
            source_path = (job.params_json or {}).get("source")
            if not source_path:
                failed += 1
                log_step(
                    job_run=job,
                    level=JobLog.Level.ERROR,
                    message="Validation source is missing in params_json['source']",
                )
                continue

            try:
                job.status = JobRun.Status.RUNNING
                job.started_at = timezone.now()
                job.save(update_fields=["status", "started_at"])
                log_step(
                    job_run=job,
                    level=JobLog.Level.INFO,
                    message=f"Validation started. source={source_path}",
                )

                result = validate_workbook(source_path)
                job.result_json = result
                job.status = JobRun.Status.SUCCESS
                job.finished_at = timezone.now()
                job.save(update_fields=["result_json", "status", "finished_at"])

                log_step(
                    job_run=job,
                    level=JobLog.Level.INFO,
                    message="Validation finished",
                    context=result.get("summary", {}),
                )
                processed += 1
            except Exception as exc:
                failed += 1
                job.status = JobRun.Status.FAILED
                job.finished_at = timezone.now()
                job.save(update_fields=["status", "finished_at"])
                log_step(
                    job_run=job,
                    level=JobLog.Level.ERROR,
                    message=f"Validation failed: {exc}",
                )

        self.message_user(
            request,
            f"Validation action done. processed={processed}, failed={failed}",
            level=messages.INFO,
        )

    @admin.action(description="Send Telegram reminders for selected jobs")
    def send_telegram_reminders_action(self, request, queryset):
        total_sent = 0
        total_skipped = 0
        total_errors = 0

        for job in queryset:
            result = send_validation_reminders_for_job(job)
            total_sent += result["sent"]
            total_skipped += result["skipped"]
            total_errors += result["errors"]

        self.message_user(
            request,
            (
                "Telegram reminders sent. "
                f"sent={total_sent}, skipped={total_skipped}, errors={total_errors}"
            ),
            level=messages.INFO,
        )



@admin.register(JobLog)
class JobLogAdmin(admin.ModelAdmin):
    list_display = ("job_run", "ts", "level", "message")
    list_filter = ("level", "ts")
    search_fields = ("message", "job_run__job_type")