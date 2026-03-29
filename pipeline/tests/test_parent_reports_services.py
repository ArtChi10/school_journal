from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from jobs.models import JobLog, JobRun
from notifications.models import NotificationEvent
from pipeline.parent_reports_job_runner import run_send_parent_reports_job
from pipeline.services_parent_reports import run_send_parent_reports_step


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SendParentReportsStepTests(TestCase):
    def test_step_sends_and_collects_statuses(self):
        with TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "output" / "pdf" / "7D" / "Ivan Ivanov.pdf"
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(b"%PDF-1.4 test")

            job = JobRun.objects.create(job_type="send_parent_reports", status=JobRun.Status.RUNNING)
            result = run_send_parent_reports_step(
                pdf_files=[{"path": str(pdf_path), "student": "Ivan Ivanov", "class_code": "7D"}],
                contacts=[
                    {
                        "student": "Ivan Ivanov",
                        "class_code": "7D",
                        "recipients": [
                            {"channel": "email", "value": "parent1@example.com"},
                            {"channel": "email", "value": "parent2@example.com"},
                        ],
                    }
                ],
                job_run=job,
            )

        self.assertEqual(result["students_total"], 1)
        self.assertEqual(result["sent_success"], 2)
        self.assertEqual(result["sent_failed"], 0)
        self.assertEqual(result["skipped_no_contact"], 0)
        self.assertEqual(result["skipped_no_pdf"], 0)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(NotificationEvent.objects.filter(status=NotificationEvent.Status.SENT).count(), 2)
        self.assertTrue(JobLog.objects.filter(job_run=job, message="Parent report sent").exists())

    def test_step_handles_no_contact_no_pdf_and_send_error(self):
        with TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "output" / "pdf" / "7D" / "Ivan Ivanov.pdf"
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(b"%PDF-1.4 test")

            with patch("pipeline.services_parent_reports.EmailMessage.send", side_effect=RuntimeError("smtp down")):
                result = run_send_parent_reports_step(
                    pdf_files=[{"path": str(pdf_path), "student": "Ivan Ivanov", "class_code": "7D"}],
                    contacts=[
                        {"student": "No Contact Kid", "class_code": "7D", "recipients": []},
                        {"student": "No Pdf Kid", "class_code": "7D", "recipients": ["parent@example.com"]},
                        {"student": "Ivan Ivanov", "class_code": "7D", "recipients": ["parent@example.com"]},
                    ],
                )

        self.assertEqual(result["students_total"], 3)
        self.assertEqual(result["sent_success"], 0)
        self.assertEqual(result["sent_failed"], 1)
        self.assertEqual(result["skipped_no_contact"], 1)
        self.assertEqual(result["skipped_no_pdf"], 1)
        self.assertIn("smtp down", " ".join((d.get("error") or "") for d in result["details"]))

    def test_repeat_run_is_marked_and_not_resent(self):
        with TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "output" / "pdf" / "7D" / "Ivan Ivanov.pdf"
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(b"%PDF-1.4 test")

            payload = {
                "pdf_files": [{"path": str(pdf_path), "student": "Ivan Ivanov", "class_code": "7D"}],
                "contacts": [{"student": "Ivan Ivanov", "class_code": "7D", "recipients": ["parent@example.com"]}],
            }
            first = run_send_parent_reports_job(**payload)
            second = run_send_parent_reports_job(**payload)

        self.assertEqual(first.result_json["sent_success"], 1)
        self.assertEqual(second.result_json["sent_success"], 0)
        self.assertEqual(second.result_json["repeated_skipped"], 1)
        self.assertEqual(len(mail.outbox), 1)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SendParentReportsCommandTests(TestCase):
    def test_command_runs_with_contacts_json(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "pdf" / "7D" / "Ivan Ivanov.pdf"
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(b"%PDF-1.4 test")

            contacts_path = tmp_path / "contacts.json"
            contacts_path.write_text(
                """
[
  {
    "student": "Ivan Ivanov",
    "class_code": "7D",
    "recipients": [
      {"channel": "email", "value": "parent@example.com"}
    ]
  }
]
                """.strip(),
                encoding="utf-8",
            )

            call_command(
                "send_parent_reports",
                "--contacts-json",
                str(contacts_path),
                "--pdf-root",
                str(tmp_path / "pdf"),
            )

        job = JobRun.objects.filter(job_type="send_parent_reports").latest("started_at")
        self.assertEqual(job.status, JobRun.Status.SUCCESS)
        self.assertEqual(job.result_json["sent_success"], 1)