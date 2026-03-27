from django.core.management.base import BaseCommand, CommandError

from pipeline.services import CriterionNormalizationError, normalize_criterion_text_with_ai


class Command(BaseCommand):
    help = "Run AI review for one criterion text and print structured feedback"

    def add_arguments(self, parser):
        parser.add_argument("--text", type=str, required=True, help="Criterion text to review")
        parser.add_argument("--model", type=str, help="Optional OpenAI model name")

    def handle(self, *args, **options):
        text = (options.get("text") or "").strip()
        model = options.get("model")

        if not text:
            raise CommandError("--text must not be empty")

        try:
            ai_comment = normalize_criterion_text_with_ai(text, model=model)
        except CriterionNormalizationError as exc:
            raise CommandError(f"AI review failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("AI comment:"))
        self.stdout.write(ai_comment)