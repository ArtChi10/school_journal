from unittest.mock import patch
from django.test import override_settings
from django.test import TestCase
from django.urls import reverse

from jobs.models import JobLog, JobRun
from notifications.models import TeacherConfirmation, TeacherContact
from pipeline.models import CriterionEntry


class TeacherConfirmationRecheckTests(TestCase):
    def setUp(self):
        self.url = reverse("telegram_webhook")

    @patch("notifications.views.send_telegram")
    @patch("notifications.recheck.evaluate_criterion_text_with_ai")
    def test_confirmation_triggers_recheck_only_for_confirming_teacher_invalid_entries(self, evaluate_mock, send_telegram_mock):
        evaluate_mock.side_effect = [
            {
                "verdict": "valid",
                "why": "Good now",
                "fix": "",
                "variants": ["Объясняет тему по шагам"],
            },
            {
                "verdict": "invalid",
                "why": "Still vague",
                "fix": "Добавьте измеримое действие",
                "variants": ["Знает тему"],
            },
        ]

        TeacherContact.objects.create(name="Teacher A", chat_id="101", is_active=True)
        TeacherContact.objects.create(name="Teacher B", chat_id="202", is_active=True)
        source_job = JobRun.objects.create(job_type="run_validation")

        a_validated = CriterionEntry.objects.create(
            class_code="4A",
            subject_name="Math",
            teacher_name="Teacher A",
            module_number=1,
            criterion_text="Criterion A1",
            validation_status=CriterionEntry.ValidationStatus.INVALID,
            needs_recheck=True,
            source_sheet_name="Math",
            source_workbook="book.xlsx",
        )
        a_still_invalid = CriterionEntry.objects.create(
            class_code="4A",
            subject_name="Math",
            teacher_name="Teacher A",
            module_number=1,
            criterion_text="Criterion A2",
            validation_status=CriterionEntry.ValidationStatus.INVALID,
            needs_recheck=True,
            source_sheet_name="Math",
            source_workbook="book.xlsx",
        )
        b_entry = CriterionEntry.objects.create(
            class_code="5B",
            subject_name="Science",
            teacher_name="Teacher B",
            module_number=2,
            criterion_text="Criterion B1",
            validation_status=CriterionEntry.ValidationStatus.INVALID,
            needs_recheck=True,
            source_sheet_name="Science",
            source_workbook="book.xlsx",
        )

        response = self.client.post(
            self.url,
            data={
                "message": {
                    "text": f"исправил {source_job.id}",
                    "chat": {"id": 101},
                }
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True, "status": "confirmed"})

        self.assertEqual(TeacherConfirmation.objects.filter(job_run=source_job).count(), 1)
        recheck_job = JobRun.objects.get(job_type="teacher_criteria_recheck")
        self.assertEqual(recheck_job.status, JobRun.Status.SUCCESS)
        self.assertEqual(recheck_job.params_json["teacher_name"], "Teacher A")

        a_validated.refresh_from_db()
        self.assertEqual(a_validated.validation_status, CriterionEntry.ValidationStatus.VALID)
        self.assertFalse(a_validated.needs_recheck)

        a_still_invalid.refresh_from_db()
        self.assertEqual(a_still_invalid.validation_status, CriterionEntry.ValidationStatus.INVALID)
        self.assertTrue(a_still_invalid.needs_recheck)

        b_entry.refresh_from_db()
        self.assertEqual(b_entry.validation_status, CriterionEntry.ValidationStatus.INVALID)
        self.assertTrue(b_entry.needs_recheck)

        failures = CriterionEntry.objects.filter(
            validation_status=CriterionEntry.ValidationStatus.INVALID,
            needs_recheck=True,
        )
        self.assertEqual(
            list(failures.order_by("criterion_text").values_list("criterion_text", flat=True)),
            ["Criterion A2", "Criterion B1"],
        )
        self.assertEqual(evaluate_mock.call_count, 2)
        send_telegram_mock.assert_called_once()
        self.assertIn("Остались невалидные критерии", send_telegram_mock.call_args.args[1])

        recheck_log = JobLog.objects.get(job_run=source_job, message="Teacher recheck triggered")
        self.assertEqual(recheck_log.context_json["cycle"], 1)

    @patch("notifications.views.send_telegram")
    @patch("notifications.recheck.evaluate_criterion_text_with_ai")
    def test_confirmation_sends_final_success_message_when_no_invalid_left(self, evaluate_mock, send_telegram_mock):
        evaluate_mock.return_value = {
            "verdict": "valid",
            "why": "Good now",
            "fix": "",
            "variants": ["Объясняет тему по шагам"],
        }

        TeacherContact.objects.create(name="Teacher A", chat_id="101", is_active=True)
        source_job = JobRun.objects.create(job_type="run_validation")
        CriterionEntry.objects.create(
            class_code="4A",
            subject_name="Math",
            teacher_name="Teacher A",
            module_number=1,
            criterion_text="Criterion A1",
            validation_status=CriterionEntry.ValidationStatus.INVALID,
            needs_recheck=True,
            source_sheet_name="Math",
            source_workbook="book.xlsx",
        )

        response = self.client.post(
            self.url,
            data={
                "message": {
                    "text": f"исправил {source_job.id}",
                    "chat": {"id": 101},
                }
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True, "status": "confirmed"})
        self.assertEqual(send_telegram_mock.call_count, 1)
        self.assertIn("всё ок", send_telegram_mock.call_args.args[1].lower())

        feedback_log = JobLog.objects.get(job_run=source_job, message="Teacher recheck feedback sent")
        self.assertEqual(feedback_log.context_json["cycle"], 1)
        self.assertEqual(feedback_log.context_json["still_invalid"], 0)

    @override_settings(TEACHER_RECHECK_MAX_CYCLES=1)
    @patch("notifications.views.send_telegram")
    @patch("notifications.recheck.evaluate_criterion_text_with_ai")
    def test_recheck_max_cycles_prevents_infinite_repeats(self, evaluate_mock, send_telegram_mock):
        evaluate_mock.return_value = {
            "verdict": "invalid",
            "why": "Still vague",
            "fix": "Добавьте измеримое действие",
            "variants": ["Знает тему"],
        }

        TeacherContact.objects.create(name="Teacher A", chat_id="101", is_active=True)
        source_job = JobRun.objects.create(job_type="run_validation")
        CriterionEntry.objects.create(
            class_code="4A",
            subject_name="Math",
            teacher_name="Teacher A",
            module_number=1,
            criterion_text="Criterion A1",
            validation_status=CriterionEntry.ValidationStatus.INVALID,
            needs_recheck=True,
            source_sheet_name="Math",
            source_workbook="book.xlsx",
        )

        first = self.client.post(
            self.url,
            data={"message": {"text": f"исправил {source_job.id}", "chat": {"id": 101}}},
            content_type="application/json",
        )
        self.assertJSONEqual(first.content, {"ok": True, "status": "confirmed"})

        second = self.client.post(
            self.url,
            data={"message": {"text": f"исправил {source_job.id}", "chat": {"id": 101}}},
            content_type="application/json",
        )
        self.assertJSONEqual(second.content, {"ok": True, "status": "repeat"})

        self.assertEqual(JobRun.objects.filter(job_type="teacher_criteria_recheck").count(), 1)
        limit_log = JobLog.objects.get(job_run=source_job, message="Teacher recheck skipped: max cycles reached")
        self.assertEqual(limit_log.context_json["cycle"], 2)
        self.assertEqual(limit_log.context_json["max_cycles"], 1)
        self.assertIn("лимит", send_telegram_mock.call_args_list[-1].args[1].lower())
