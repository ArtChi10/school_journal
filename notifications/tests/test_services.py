import json
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from django.test import TestCase, override_settings

from jobs.models import JobLog, JobRun
from notifications.services import TelegramSendError, send_telegram


class SendTelegramTests(TestCase):
    def setUp(self):
        self.job_run = JobRun.objects.create(job_type="test_job")

    @override_settings(TELEGRAM_BOT_TOKEN="test-token")
    @patch("notifications.services.request.urlopen")
    def test_send_success_writes_structured_success_log(self, urlopen_mock):
        response = MagicMock()
        response.read.return_value = json.dumps({"ok": True, "result": {"message_id": 1}}).encode("utf-8")
        urlopen_mock.return_value.__enter__.return_value = response

        result = send_telegram("123", "hello", timeout=5, job_run_id=self.job_run.id)

        self.assertTrue(result["ok"])
        urlopen_mock.assert_called_once()
        self.assertEqual(urlopen_mock.call_args.kwargs["timeout"], 5)

        logs = JobLog.objects.filter(job_run=self.job_run).order_by("ts")
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.level, JobLog.Level.INFO)
        self.assertEqual(log.context_json["job_run_id"], str(self.job_run.id))
        self.assertEqual(log.context_json["chat_id"], "123")
        self.assertEqual(log.context_json["attempt"], 1)
        self.assertEqual(log.context_json["status"], "success")
        self.assertEqual(log.context_json["error_message"], "")

    @override_settings(TELEGRAM_BOT_TOKEN="test-token")
    @patch("notifications.services.time.sleep")
    @patch("notifications.services.request.urlopen")
    def test_retry_after_error_then_success(self, urlopen_mock, sleep_mock):
        success_response = MagicMock()
        success_response.read.return_value = json.dumps({"ok": True, "result": {"message_id": 2}}).encode("utf-8")

        urlopen_mock.side_effect = [
            URLError("network down"),
            MagicMock(__enter__=MagicMock(return_value=success_response), __exit__=MagicMock(return_value=False)),
        ]

        result = send_telegram("456", "retry", retries=1, job_run_id=self.job_run.id)

        self.assertTrue(result["ok"])
        self.assertEqual(urlopen_mock.call_count, 2)
        sleep_mock.assert_called_once_with(1)

        logs = list(JobLog.objects.filter(job_run=self.job_run).order_by("ts"))
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].level, JobLog.Level.ERROR)
        self.assertEqual(logs[0].context_json["attempt"], 1)
        self.assertEqual(logs[0].context_json["status"], "error")
        self.assertIn("network down", logs[0].context_json["error_message"])

        self.assertEqual(logs[1].level, JobLog.Level.INFO)
        self.assertEqual(logs[1].context_json["attempt"], 2)
        self.assertEqual(logs[1].context_json["status"], "success")

    @override_settings(TELEGRAM_BOT_TOKEN="test-token")
    @patch("notifications.services.time.sleep")
    @patch("notifications.services.request.urlopen", side_effect=URLError("timeout"))
    def test_raises_controlled_exception_when_all_attempts_fail(self, _urlopen_mock, sleep_mock):
        with self.assertRaises(TelegramSendError):
            send_telegram("789", "boom", retries=1, job_run_id=self.job_run.id)

        sleep_mock.assert_called_once_with(1)
        logs = list(JobLog.objects.filter(job_run=self.job_run).order_by("ts"))
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].context_json["attempt"], 1)
        self.assertEqual(logs[1].context_json["attempt"], 2)
        self.assertEqual(logs[0].context_json["status"], "error")
        self.assertEqual(logs[1].context_json["status"], "error")