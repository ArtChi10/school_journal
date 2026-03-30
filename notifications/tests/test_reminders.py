from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from jobs.models import JobLog, JobRun
from notifications.models import NotificationEvent, TeacherContact
from notifications.reminders import run_validation_reminders_job, send_validation_reminders_for_job
from notifications.services import TelegramSendError
from pipeline.models import CriterionEntry


class SendValidationRemindersTests(TestCase):
    def setUp(self):
        self.job_run = JobRun.objects.create(job_type="run_validation", result_json={"issues": []})
        self._create_entries()

    def _create_entries(self):
        # Teacher A has both valid and invalid criteria.
        CriterionEntry.objects.create(
            class_code="5A",
            subject_name="Math",
            teacher_name="Teacher A",
            module_number=1,
            criterion_text="Решает квадратные уравнения",
            validation_status=CriterionEntry.ValidationStatus.VALID,
            source_sheet_name="Math",
            source_workbook="w.xlsx",
        )
        CriterionEntry.objects.create(
            class_code="5A",
            subject_name="Math",
            teacher_name="Teacher A",
            module_number=1,
            criterion_text="Понимает геометрию",
            validation_status=CriterionEntry.ValidationStatus.INVALID,
            ai_fix_suggestion="Добавьте измеримый глагол и результат обучения",
            source_sheet_name="Math",
            source_workbook="w.xlsx",
        )
        CriterionEntry.objects.create(
            class_code="6B",
            subject_name="Physics",
            teacher_name="Teacher A",
            module_number=2,
            criterion_text="Пустой критерий",
            validation_status=CriterionEntry.ValidationStatus.RECHECK,
            ai_why="Формулировка не содержит проверяемого действия",
            source_sheet_name="Physics",
            source_workbook="w.xlsx",
        )
        # Teacher B has invalid criteria (no contact -> skipped).
        CriterionEntry.objects.create(
            class_code="6A",
            subject_name="History",
            teacher_name="Teacher B",
            module_number=3,
            criterion_text="Знает эпоху",
            validation_status=CriterionEntry.ValidationStatus.INVALID,
            ai_fix_suggestion="Уточните результат: называет 3 причины и 3 последствия",
            source_sheet_name="History",
            source_workbook="w.xlsx",
        )
        # Teacher C only valid criteria -> no reminder.
        CriterionEntry.objects.create(
            class_code="7A",
            subject_name="Biology",
            teacher_name="Teacher C",
            module_number=1,
            criterion_text="Определяет клеточные органоиды",
            validation_status=CriterionEntry.ValidationStatus.VALID,
            source_sheet_name="Biology",
            source_workbook="w.xlsx",
        )

    @patch("notifications.reminders.send_telegram")
    def test_groups_by_teacher_and_sends_single_message_per_teacher(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        result = send_validation_reminders_for_job(self.job_run)

        self.assertEqual(result, {"sent": 1, "skipped": 1, "errors": 0})
        send_telegram_mock.assert_called_once()

        call_args = send_telegram_mock.call_args
        self.assertEqual(call_args.args[0], "111")
        message_text = call_args.args[1]
        self.assertIn("Teacher A", message_text)
        self.assertIn("Проверено критериев: 3", message_text)
        self.assertIn("Хорошие критерии", message_text)
        self.assertIn("Невалидные критерии", message_text)
        self.assertIn("Подсказка AI", message_text)
        self.assertIn("5A / Math", message_text)
        self.assertIn("6B / Physics", message_text)
        self.assertEqual(NotificationEvent.objects.filter(job_run=self.job_run).count(), 2)


    @patch("notifications.reminders.send_telegram", side_effect=TelegramSendError("boom"))
    def test_logs_errors_when_telegram_fails(self, _send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        result = send_validation_reminders_for_job(self.job_run)

        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["errors"], 1)

        error_log = JobLog.objects.filter(job_run=self.job_run, level=JobLog.Level.ERROR).first()
        self.assertIsNotNone(error_log)
        self.assertIn("Failed reminder for Teacher A", error_log.message)


    @patch("notifications.reminders.send_telegram")
    def test_sends_admin_summary_when_configured(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)
        with self.settings(ADMIN_LOG_CHAT_ID="999"):
            result = send_validation_reminders_for_job(self.job_run)

        self.assertEqual(result, {"sent": 1, "skipped": 1, "errors": 0})
        self.assertEqual(send_telegram_mock.call_count, 2)
        admin_call = send_telegram_mock.call_args_list[1]
        self.assertEqual(admin_call.args[0], "999")
        self.assertIn("Validation summary", admin_call.args[1])
        self.assertIn("Teacher A", admin_call.args[1])




    @patch("notifications.reminders.send_telegram")
    def test_does_not_send_duplicate_reminder_for_same_issues_hash(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        first_result = send_validation_reminders_for_job(self.job_run)
        second_result = send_validation_reminders_for_job(self.job_run)
        self.assertEqual(first_result, {"sent": 1, "skipped": 1, "errors": 0})
        self.assertEqual(second_result, {"sent": 0, "skipped": 2, "errors": 0})
        send_telegram_mock.assert_called_once()

    @patch("notifications.reminders.send_telegram")
    def test_sends_again_when_payload_hash_changes(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        send_validation_reminders_for_job(self.job_run)
        updated = CriterionEntry.objects.get(teacher_name="Teacher A",
                                             validation_status=CriterionEntry.ValidationStatus.INVALID)
        updated.ai_fix_suggestion = "Новая подсказка"
        updated.save(update_fields=["ai_fix_suggestion", "updated_at"])
        result = send_validation_reminders_for_job(self.job_run)

        self.assertEqual(result["sent"], 1)
        self.assertEqual(send_telegram_mock.call_count, 2)


class SendValidationRemindersCommandTests(TestCase):
    @patch("notifications.reminders.send_telegram")
    def test_command_accepts_job_id_and_prints_summary(self, _send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)
        CriterionEntry.objects.create(
            class_code="5A",
            subject_name="Math",
            teacher_name="Teacher A",
            module_number=1,
            criterion_text="Понимает геометрию",
            validation_status=CriterionEntry.ValidationStatus.INVALID,
            ai_fix_suggestion="Уточнить глагол",
            source_sheet_name="Math",
            source_workbook="w.xlsx",
        )
        job_run = JobRun.objects.create(job_type="run_validation", result_json={"issues": []})

        from io import StringIO

        out = StringIO()
        call_command("send_validation_reminders", "--job-id", str(job_run.id), stdout=out)

        output = out.getvalue()
        self.assertIn("sent=1, skipped=0, errors=0", output)



class RunValidationRemindersJobTests(TestCase):
    @patch("notifications.reminders.send_telegram")
    def test_creates_separate_reminder_job_with_logs(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)
        CriterionEntry.objects.create(
            class_code="7A",
            subject_name="Math",
            teacher_name="Teacher A",
            module_number=1,
            criterion_text="Нет измеримого действия",
            validation_status=CriterionEntry.ValidationStatus.INVALID,
            ai_fix_suggestion="Добавьте измеримый результат",
            source_sheet_name="Math",
            source_workbook="w.xlsx",
        )
        source_job = JobRun.objects.create(job_type="run_validation", result_json={"issues": []})
        reminder_job = run_validation_reminders_job(source_job_run=source_job)

        self.assertEqual(reminder_job.job_type, "send_validation_reminders")
        self.assertEqual(reminder_job.status, JobRun.Status.SUCCESS)
        self.assertEqual(reminder_job.result_json["summary"], {"sent": 1, "skipped": 0, "errors": 0})
        self.assertTrue(JobLog.objects.filter(job_run=reminder_job, message="Reminder job started").exists())
        send_telegram_mock.assert_called_once()
