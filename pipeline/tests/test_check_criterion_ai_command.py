from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from pipeline.services import CriterionNormalizationError


class CheckCriterionAICommandTests(SimpleTestCase):
    def test_prints_ai_comment_for_valid_text(self):
        out = StringIO()
        with patch(
            "pipeline.management.commands.check_criterion_ai.normalize_criterion_text_with_ai",
            return_value="Вердикт: подходит.",
        ) as mock_review:
            call_command("check_criterion_ai", "--text", "Решает задачи на проценты", stdout=out)

        output = out.getvalue()
        self.assertIn("AI comment:", output)
        self.assertIn("Вердикт: подходит.", output)
        mock_review.assert_called_once_with("Решает задачи на проценты", model=None)

    def test_raises_command_error_when_ai_fails(self):
        with patch(
            "pipeline.management.commands.check_criterion_ai.normalize_criterion_text_with_ai",
            side_effect=CriterionNormalizationError("boom"),
        ):
            with self.assertRaisesMessage(CommandError, "AI review failed: boom"):
                call_command("check_criterion_ai", "--text", "Критерий")