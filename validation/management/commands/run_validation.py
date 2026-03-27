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
        summary = job_run.result_json.get("summary", {})
        tables = job_run.result_json.get("tables", [])
        failed_tables = [table for table in tables if table.get("status") == "failed"]
        self.stdout.write(
            self.style.SUCCESS(
                "Validation job created: "
                f"id={job_run.id} status={job_run.status} "
                f"tables={summary.get('tables_total', 0)} "
                f"ok={summary.get('tables_success', 0)} "
                f"failed={summary.get('tables_failed', 0)}"
            )
        )
        if failed_tables:
            self.stdout.write(self.style.WARNING("Failed tables details:"))
            for table in failed_tables[:5]:
                self.stdout.write(
                    self.style.WARNING(
                        f"- link_id={table.get('link_id')} class={table.get('class_code')} error={table.get('error')}"
                    )
                )