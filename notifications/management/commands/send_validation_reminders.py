from django.core.management.base import BaseCommand, CommandError

from jobs.models import JobRun
from notifications.reminders import send_validation_reminders_for_job


class Command(BaseCommand):
    help = "Send grouped Telegram reminders to teachers for a validation job"

    def add_arguments(self, parser):
        parser.add_argument("--job-id", required=True, type=str, help="JobRun UUID")

    def handle(self, *args, **options):
        job_id = options["job_id"]
        try:
            job_run = JobRun.objects.get(id=job_id)
        except JobRun.DoesNotExist as exc:
            raise CommandError(f"JobRun not found: {job_id}") from exc

        result = send_validation_reminders_for_job(job_run)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. sent={result['sent']}, skipped={result['skipped']}, errors={result['errors']}"
            )
        )