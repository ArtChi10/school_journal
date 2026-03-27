from django.core.management.base import BaseCommand, CommandError

from validation.job_runner import run_validation_job


class Command(BaseCommand):
    help = "Run workbook validation for one link, one class, or all active links"

    def add_arguments(self, parser):
        parser.add_argument("--link-id", type=int, help="ClassSheetLink id")
        parser.add_argument("--class-code", type=str, help="Class code (validates all active links for class)")
        parser.add_argument("--all-active", action="store_true", help="Validate all active links")

    def handle(self, *args, **options):
        link_id = options.get("link_id")
        class_code = options.get("class_code")
        all_active = options.get("all_active")

        selected_count = sum(bool(v) for v in [link_id, class_code, all_active])
        if selected_count != 1:
            raise CommandError("Specify exactly one option: --link-id or --class-code or --all-active")

        job_run = run_validation_job(link_id=link_id, class_code=class_code, all_active=all_active)
        self.stdout.write(
            self.style.SUCCESS(
                f"Validation job created: id={job_run.id} status={job_run.status} tables={job_run.result_json.get('summary', {}).get('tables_total', 0)}"
            )
        )