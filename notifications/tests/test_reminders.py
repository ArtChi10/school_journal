from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from jobs.models import JobLog, JobRun
from notifications.models import NotificationEvent, TeacherContact
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
        self.assertIn("ADMIN_LOG_CHAT_ID is not configured; admin summary skipped", log_messages)
        self.assertEqual(NotificationEvent.objects.filter(job_run=self.job_run).count(), 4)
        self.assertTrue(
            NotificationEvent.objects.filter(
                job_run=self.job_run,
                teacher_name="Teacher A",
                status=NotificationEvent.Status.SENT,
                channel=NotificationEvent.Channel.TELEGRAM,
            ).exists()
        )
        self.assertTrue(
            NotificationEvent.objects.filter(
                job_run=self.job_run,
                teacher_name="Teacher B",
                status=NotificationEvent.Status.SKIPPED,
            ).exists()
        )

    @patch("notifications.reminders.send_telegram", side_effect=TelegramSendError("boom"))
    def test_logs_errors_when_telegram_fails(self, _send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        result = send_validation_reminders_for_job(self.job_run)

        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["errors"], 1)

        error_log = JobLog.objects.filter(job_run=self.job_run, level=JobLog.Level.ERROR).first()
        self.assertIsNotNone(error_log)
        self.assertIn("Failed reminder for Teacher A", error_log.message)
        self.assertTrue(
            NotificationEvent.objects.filter(
                job_run=self.job_run,
                teacher_name="Teacher A",
                status=NotificationEvent.Status.ERROR,
            ).exists()
        )

    @patch("notifications.reminders.send_telegram")
    def test_can_filter_notification_events_by_job_run_and_teacher_name(self, _send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)
        send_validation_reminders_for_job(self.job_run)

        filtered = NotificationEvent.objects.filter(job_run=self.job_run, teacher_name="Teacher A")
        self.assertEqual(filtered.count(), 1)
        self.assertEqual(filtered.first().status, NotificationEvent.Status.SENT)

    @patch("notifications.reminders.send_telegram")
    def test_sends_admin_summary_when_configured(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)
        with self.settings(ADMIN_LOG_CHAT_ID="999"):
            result = send_validation_reminders_for_job(self.job_run)

        self.assertEqual(result, {"sent": 1, "skipped": 3, "errors": 0})
        self.assertEqual(send_telegram_mock.call_count, 2)
        admin_call = send_telegram_mock.call_args_list[1]
        self.assertEqual(admin_call.args[0], "999")
        self.assertIn("Validation summary (job_id=", admin_call.args[1])
        self.assertIn("• sent: 1", admin_call.args[1])
        self.assertIn("Teacher A", admin_call.args[1])
        self.assertIn("5A / Math", admin_call.args[1])
        self.assertIn("Нет оценки у ученика", admin_call.args[1])

        payload_log = JobLog.objects.get(job_run=self.job_run, message="Validation admin summary payload")
        self.assertEqual(payload_log.context_json["total_teachers"], 4)
        self.assertEqual(payload_log.context_json["sent"], 1)

        status_log = JobLog.objects.get(job_run=self.job_run, message="Admin summary sent")
        self.assertEqual(status_log.context_json["status"], "sent")
        self.assertEqual(status_log.context_json["chat_id"], "999")

    @patch("notifications.reminders.send_telegram")
    def test_admin_summary_error_does_not_fail_job(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        def _send_side_effect(chat_id, *_args, **_kwargs):
            if chat_id == "999":
                raise TelegramSendError("admin down")
            return {"ok": True}

        send_telegram_mock.side_effect = _send_side_effect

        with self.settings(ADMIN_LOG_CHAT_ID="999"):
            result = send_validation_reminders_for_job(self.job_run)

        self.assertEqual(result, {"sent": 1, "skipped": 3, "errors": 0})
        self.assertEqual(send_telegram_mock.call_count, 2)
        error_log = JobLog.objects.get(job_run=self.job_run, message__startswith="Failed to send admin summary:")
        self.assertIn("admin down", error_log.message)

    @patch("notifications.reminders.send_telegram")
    def test_skip_reasons_no_chat_and_inactive(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)
        TeacherContact.objects.create(name="Teacher C", chat_id="", is_active=True)
        TeacherContact.objects.create(name="Teacher D", chat_id="444", is_active=False)

        result = send_validation_reminders_for_job(self.job_run)

        self.assertEqual(result, {"sent": 1, "skipped": 3, "errors": 0})
        send_telegram_mock.assert_called_once()

        warnings = JobLog.objects.filter(job_run=self.job_run, level=JobLog.Level.WARNING)
        reasons = {log.context_json.get("reason") for log in warnings if log.context_json.get("reason")}
        self.assertEqual(reasons, {"no_contact", "no_chat_id", "inactive"})

    @patch("notifications.reminders.send_telegram")
    def test_does_not_send_duplicate_reminder_for_same_issues_hash(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        first_result = send_validation_reminders_for_job(self.job_run)
        second_result = send_validation_reminders_for_job(self.job_run)

        self.assertEqual(first_result, {"sent": 1, "skipped": 3, "errors": 0})
        self.assertEqual(second_result, {"sent": 0, "skipped": 4, "errors": 0})
        send_telegram_mock.assert_called_once()
        self.assertTrue(
            JobLog.objects.filter(
                job_run=self.job_run,
                message="Reminder skipped for Teacher A: skipped_duplicate",
            ).exists()
        )
        self.assertEqual(
            NotificationEvent.objects.filter(
                job_run=self.job_run,
                teacher_name="Teacher A",
                payload_hash=NotificationEvent.objects.filter(
                    job_run=self.job_run,
                    teacher_name="Teacher A",
                    status=NotificationEvent.Status.SENT,
                )
                .values_list("payload_hash", flat=True)
                .first(),
            ).count(),
            2,
        )

    @patch("notifications.reminders.send_telegram")
    def test_sends_again_when_issues_payload_hash_changes(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        send_validation_reminders_for_job(self.job_run)
        self.job_run.result_json["issues"].append(
            {
                "teacher_name": "Teacher A",
                "class_code": "5A",
                "subject_name": "Math",
                "severity": "warning",
                "message": "Новая ошибка",
            }
        )
        self.job_run.save(update_fields=["result_json"])

        result = send_validation_reminders_for_job(self.job_run)

        self.assertEqual(result["sent"], 1)
        self.assertEqual(send_telegram_mock.call_count, 2)
        sent_hashes = list(
            NotificationEvent.objects.filter(
                job_run=self.job_run,
                teacher_name="Teacher A",
                status=NotificationEvent.Status.SENT,
            ).values_list("payload_hash", flat=True)
        )
        self.assertEqual(len(sent_hashes), 2)
        self.assertNotEqual(sent_hashes[0], sent_hashes[1])

    @patch("notifications.reminders.send_telegram")
    def test_legacy_issue_payload_without_new_context_fields_still_works(self, send_telegram_mock):
        legacy_job_run = JobRun.objects.create(
            job_type="run_validation",
            result_json={
                "issues": [
                    {
                        "teacher_name": "Teacher Legacy",
                        "class": "9C",
                        "subject": "Geometry",
                        "severity": "warning",
                        "message": "Legacy payload issue",
                    }
                ]
            },
        )
        TeacherContact.objects.create(name="Teacher Legacy", chat_id="9991", is_active=True)

        result = send_validation_reminders_for_job(legacy_job_run)

        self.assertEqual(result, {"sent": 1, "skipped": 0, "errors": 0})
        send_telegram_mock.assert_called_once()
        self.assertIn("9C / Geometry", send_telegram_mock.call_args.args[1])

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
