from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

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