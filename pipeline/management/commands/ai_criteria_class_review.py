from django.core.management.base import BaseCommand, CommandError

from pipeline.ai_criteria_review import run_ai_criteria_class_review_job


class Command(BaseCommand):
    help = "Run batch AI criteria review for one class or all active classes."

    def add_arguments(self, parser):
        parser.add_argument("--class-code", type=str, help="Class code")
        parser.add_argument("--all-active", action="store_true", help="Review all active classes")

    def handle(self, *args, **options):
        class_code = options.get("class_code")
        all_active = options.get("all_active")
        if sum(bool(value) for value in [class_code, all_active]) != 1:
            raise CommandError("Specify exactly one option: --class-code or --all-active")

        job_run = run_ai_criteria_class_review_job(class_code=class_code, all_active=all_active)
        summary = job_run.result_json.get("summary", {})
        self.stdout.write(
            self.style.SUCCESS(
                "AI criteria review job created: "
                f"id={job_run.id} status={job_run.status} "
                f"classes={summary.get('classes_checked', 0)} "
                f"criteria_sent_to_ai={summary.get('criteria_sent_to_ai', 0)} "
                f"problems={summary.get('criteria_problem', 0)}"
            )
        )
