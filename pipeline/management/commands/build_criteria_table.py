from django.core.management.base import BaseCommand, CommandError

from pipeline.job_runner import run_build_criteria_job


class Command(BaseCommand):
    help = "Build criteria table for one link, one class, or all active links"

    def add_arguments(self, parser):
        parser.add_argument("--link-id", type=int, help="ClassSheetLink id")
        parser.add_argument("--class-code", type=str, help="Class code (all active links for class)")
        parser.add_argument("--all-active", action="store_true", help="Build criteria for all active links")

    def handle(self, *args, **options):
        link_id = options.get("link_id")
        class_code = options.get("class_code")
        all_active = options.get("all_active")

        selected_count = sum(bool(v) for v in [link_id, class_code, all_active])
        if selected_count != 1:
            raise CommandError("Specify exactly one option: --link-id or --class-code or --all-active")

        job_run = run_build_criteria_job(link_id=link_id, class_code=class_code, all_active=all_active)
        summary = job_run.result_json.get("summary", {})
        self.stdout.write(
            self.style.SUCCESS(
                "Criteria build job created: "
                f"id={job_run.id} status={job_run.status} "
                f"total_sheets={summary.get('total_sheets', 0)} total_criteria={summary.get('total_criteria', 0)} "
                f"ai_ok={summary.get('ai_ok', 0)} ai_failed={summary.get('ai_failed', 0)}"
            )
        )