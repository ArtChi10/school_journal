from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from jobs.models import JobLog, JobRun
from notifications.models import TeacherContact
from notifications.reminders import send_validation_reminders_for_job
from notifications.services import TelegramSendError


class SendValidationRemindersTests(TestCase):
    def setUp(self):
        self.job_run = JobRun.objects.create(
            job_type="run_validation",
            result_json={
                "issues": [
                    {
                        "teacher_name": "Teacher A",
                        "class_code": "5A",
                        "subject_name": "Math",
                        "severity": "critical",
                        "message": "Нет оценки у ученика",
                    },
                    {
                        "teacher_name": "Teacher A",
                        "class_code": "5A",
                        "subject_name": "Math",
                        "severity": "warning",
                        "message": "Нет оценки у ученика",
                    },
                    {
                        "teacher_name": "Teacher A",
                        "class_code": "6B",
                        "subject_name": "Physics",
                        "severity": "warning",
                        "message": "Пустой комментарий",
                    },
                    {
                        "teacher_name": "Teacher B",
                        "class_code": "6A",
                        "subject_name": "History",
                        "severity": "critical",
                        "message": "Нет темы урока",
                    },
                    {
                        "teacher_name": "Teacher C",
                        "class_code": "7A",
                        "subject_name": "Biology",
                        "severity": "warning",
                        "message": "Ошибка формата даты",
                    },
                    {
                        "teacher_name": "Teacher D",
                        "class_code": "8A",
                        "subject_name": "Chemistry",
                        "severity": "warning",
                        "message": "Нет домашнего задания",
                    },
                ]
            },
        )

    @patch("notifications.reminders.send_telegram")
    def test_groups_by_teacher_and_sends_single_message_per_teacher(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        result = send_validation_reminders_for_job(self.job_run)

        self.assertEqual(result, {"sent": 1, "skipped": 3, "errors": 0})
        send_telegram_mock.assert_called_once()

        call_args = send_telegram_mock.call_args
        self.assertEqual(call_args.args[0], "111")
        message_text = call_args.args[1]
        self.assertIn("Teacher A", message_text)
        self.assertIn("5A / Math", message_text)
        self.assertIn("6B / Physics", message_text)
        self.assertIn("Нет оценки у ученика (x2)", message_text)
        self.assertIn("исправьте и подтвердите", message_text)

        log_messages = list(JobLog.objects.filter(job_run=self.job_run).values_list("message", flat=True))
        self.assertIn("Reminder sent to Teacher A", log_messages)
        self.assertIn("Reminder skipped for Teacher B: no_contact", log_messages)

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
    def test_skip_reasons_no_chat_and_inactive(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)
        TeacherContact.objects.create(name="Teacher C", chat_id="", is_active=True)
        TeacherContact.objects.create(name="Teacher D", chat_id="444", is_active=False)

        result = send_validation_reminders_for_job(self.job_run)

        self.assertEqual(result, {"sent": 1, "skipped": 3, "errors": 0})
        send_telegram_mock.assert_called_once()

        warnings = JobLog.objects.filter(job_run=self.job_run, level=JobLog.Level.WARNING)
        reasons = {log.context_json.get("reason") for log in warnings}
        self.assertEqual(reasons, {"no_contact", "no_chat_id", "inactive"})


class SendValidationRemindersCommandTests(TestCase):
    @patch("notifications.reminders.send_telegram")
    def test_command_accepts_job_id_and_prints_summary(self, _send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)
        job_run = JobRun.objects.create(
            job_type="run_validation",
            result_json={
                "issues": [
                    {
                        "teacher_name": "Teacher A",
                        "class_code": "5A",
                        "subject_name": "Math",
                        "severity": "critical",
                        "message": "Нет оценки",
                    }
                ]
            },
        )

        from io import StringIO

        out = StringIO()
        call_command("send_validation_reminders", "--job-id", str(job_run.id), stdout=out)

        output = out.getvalue()
        self.assertIn("sent=1, skipped=0, errors=0", output)

    def test_command_raises_error_for_unknown_job_id(self):
        from django.core.management.base import CommandError

        with self.assertRaisesMessage(CommandError, "JobRun not found"):
            call_command("send_validation_reminders", "--job-id", "00000000-0000-0000-0000-000000000000")
