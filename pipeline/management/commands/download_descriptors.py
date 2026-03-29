from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from jobs.models import JobRun
from pipeline.services_download import run_download_descriptors_step


class Command(BaseCommand):
    help = "Download descriptor workbooks for one class or all active links"

    def add_arguments(self, parser):
        parser.add_argument("--class-code", type=str, help="Class code (all active links for class)")
        parser.add_argument("--all-active", action="store_true", help="Download for all active links")

    def handle(self, *args, **options):
        class_code = options.get("class_code")
        all_active = options.get("all_active")

        selected_count = sum(bool(v) for v in [class_code, all_active])
        if selected_count != 1:
            raise CommandError("Specify exactly one option: --class-code or --all-active")

        job_run = JobRun.objects.create(
            job_type="download_descriptors",
            status=JobRun.Status.RUNNING,
            started_at=timezone.now(),
            params_json={"class_code": class_code, "all_active": all_active},
        )

        links = None
        if class_code:
            links = None
        result = run_download_descriptors_step(class_code=class_code if class_code else None, links=links, job_run=job_run)

        if result["downloads_success"] == 0:
            status = JobRun.Status.FAILED
        elif result["downloads_failed"] > 0:
            status = JobRun.Status.PARTIAL
        else:
            status = JobRun.Status.SUCCESS

        job_run.status = status
        job_run.finished_at = timezone.now()
        job_run.result_json = result
        job_run.save(update_fields=["status", "finished_at", "result_json"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Download job created: id={job_run.id} status={status} "
                f"downloads_total={result['downloads_total']} "
                f"downloads_success={result['downloads_success']} downloads_failed={result['downloads_failed']}"
            )
        )