from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from jobs.models import JobLog, JobRun
from notifications.models import TeacherContact


class TelegramWebhookTests(TestCase):
    def setUp(self):
        self.url = reverse("telegram_webhook")

    @patch("notifications.views.send_telegram")
    def test_start_register_binds_contact_and_invalidates_token(self, send_telegram_mock):
        contact = TeacherContact.objects.create(
            name="Иван Иванов",
            registration_token="abc123",
            is_active=False,
            chat_id="",
        )

        response = self.client.post(
            self.url,
            data={
                "message": {
                    "text": "/start register_abc123",
                    "chat": {"id": 123456789},
                }
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"ok": True, "status": "registered", "teacher": "Иван Иванов"},
        )

        contact.refresh_from_db()
        self.assertEqual(contact.chat_id, "123456789")
        self.assertTrue(contact.is_active)
        self.assertIsNotNone(contact.last_seen_at)
        self.assertIsNone(contact.registration_token)
        send_telegram_mock.assert_called_once_with(
            "123456789", "Регистрация успешна. Контакт привязан: Иван Иванов."
        )

    @patch("notifications.views.send_telegram")
    def test_invalid_token_sends_error_message(self, send_telegram_mock):
        response = self.client.post(
            self.url,
            data={
                "message": {
                    "text": "/start register_unknown",
                    "chat": {"id": 987654321},
                }
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True, "status": "token_not_found"})
        send_telegram_mock.assert_called_once_with(
            "987654321", "Ссылка регистрации недействительна. Обратитесь к администратору."
        )

    def test_teacher_confirmation_with_explicit_job_id_is_saved(self):
        teacher = TeacherContact.objects.create(name="Teacher A", chat_id="123", is_active=True)
        job_run = JobRun.objects.create(job_type="run_validation")

        response = self.client.post(
            self.url,
            data={
                "message": {
                    "text": f"исправил {job_run.id}",
                    "chat": {"id": 123},
                }
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True, "status": "confirmed"})

        teacher.refresh_from_db()
        self.assertIsNotNone(teacher.last_seen_at)

        confirmation = job_run.teacher_confirmations.get()
        self.assertEqual(confirmation.teacher_name, "Teacher A")
        self.assertEqual(confirmation.chat_id, "123")
        self.assertEqual(confirmation.status, "confirmed")
        self.assertEqual(confirmation.message_text, f"исправил {job_run.id}")

        confirmation_log = JobLog.objects.get(job_run=job_run, message="Teacher confirmation received")
        self.assertFalse(confirmation_log.context_json["is_repeat"])
        self.assertEqual(confirmation_log.context_json["explicit_job_id"], str(job_run.id))

    def test_teacher_confirmation_falls_back_to_latest_reminder_job_and_repeat_updates_record(self):
        TeacherContact.objects.create(name="Teacher B", chat_id="456", is_active=True)
        first_job = JobRun.objects.create(job_type="run_validation")
        second_job = JobRun.objects.create(job_type="run_validation")
        JobLog.objects.create(
            job_run=first_job,
            level=JobLog.Level.INFO,
            message="Reminder sent to Teacher B",
            context_json={"teacher": "Teacher B", "chat_id": "456"},
        )
        JobLog.objects.create(
            job_run=second_job,
            level=JobLog.Level.INFO,
            message="Reminder sent to Teacher B",
            context_json={"teacher": "Teacher B", "chat_id": "456"},
        )

        first_response = self.client.post(
            self.url,
            data={"message": {"text": "готово", "chat": {"id": 456}}},
            content_type="application/json",
        )
        self.assertJSONEqual(first_response.content, {"ok": True, "status": "confirmed"})

        second_response = self.client.post(
            self.url,
            data={"message": {"text": "done", "chat": {"id": 456}}},
            content_type="application/json",
        )
        self.assertJSONEqual(second_response.content, {"ok": True, "status": "repeat"})

        confirmations = second_job.teacher_confirmations.all()
        self.assertEqual(confirmations.count(), 1)
        self.assertEqual(confirmations.first().message_text, "done")

        logs = JobLog.objects.filter(job_run=second_job, message="Teacher confirmation received").order_by("ts")
        self.assertEqual(logs.count(), 2)
        self.assertFalse(logs[0].context_json["is_repeat"])
        self.assertTrue(logs[1].context_json["is_repeat"])

    def test_non_confirmation_message_is_ignored_and_logged(self):
        TeacherContact.objects.create(name="Teacher C", chat_id="777", is_active=True)
        job_run = JobRun.objects.create(job_type="run_validation")
        JobLog.objects.create(
            job_run=job_run,
            level=JobLog.Level.INFO,
            message="Reminder sent to Teacher C",
            context_json={"teacher": "Teacher C", "chat_id": "777"},
        )

        response = self.client.post(
            self.url,
            data={"message": {"text": "ок, посмотрю позже", "chat": {"id": 777}}},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True, "status": "ignored"})
        self.assertEqual(job_run.teacher_confirmations.count(), 0)
        ignored_log = JobLog.objects.get(job_run=job_run, message="Teacher message ignored")
        self.assertEqual(ignored_log.context_json["reason"], "not_confirmation_keyword")
