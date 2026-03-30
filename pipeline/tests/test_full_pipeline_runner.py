from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from jobs.models import JobLog, JobRun
from pipeline.full_pipeline_runner import _resolve_contacts, run_full_pipeline
from pipeline.models import ParentContact


class FullPipelineRunnerTests(TestCase):
    @patch("pipeline.full_pipeline_runner._resolve_contacts")
    @patch("pipeline.full_pipeline_runner.run_send_parent_reports_job")
    @patch("pipeline.full_pipeline_runner.run_convert_docx_to_pdf_step")
    @patch("pipeline.full_pipeline_runner.run_generate_docx_job")
    @patch("pipeline.full_pipeline_runner.run_build_criteria_job")
    @patch("pipeline.full_pipeline_runner.run_download_descriptors_step")
    def test_run_full_pipeline_success(
        self,
        mocked_download,
        mocked_build,
        mocked_docx,
        mocked_pdf,
        mocked_parent,
        mocked_contacts,
    ):
        mocked_download.return_value = {
            "downloads_total": 1,
            "downloads_success": 1,
            "downloads_failed": 0,
            "files": [{"status": "success", "path": "/tmp/a.xlsx"}],
        }
        mocked_build.return_value = JobRun(status=JobRun.Status.SUCCESS, id="b1", result_json={"summary": {"total_sheets": 1}})
        mocked_docx.return_value = JobRun(
            status=JobRun.Status.SUCCESS,
            id="d1",
            result_json={"docx_total": 1, "docx_success": 1, "docx_failed": 0, "files": ["/tmp/a.docx"]},
        )
        mocked_pdf.return_value = {
            "pdf_total": 1,
            "pdf_success": 1,
            "pdf_failed": 0,
            "pdf_files": [{"path": "/tmp/a.pdf", "class_code": "4A", "student": "Student A"}],
        }
        mocked_contacts.return_value = [{"student": "Student A", "class_code": "4A", "recipients": [{"channel": "email", "value": "a@example.com"}]}]
        mocked_parent.return_value = JobRun(
            status=JobRun.Status.SUCCESS,
            id="p1",
            result_json={"students_total": 1, "sent_success": 1, "sent_failed": 0, "skipped_no_contact": 0, "skipped_no_pdf": 0},
        )

        job = run_full_pipeline()

        self.assertEqual(job.status, JobRun.Status.SUCCESS)
        self.assertEqual(job.result_json["summary"]["steps_total"], 5)
        self.assertEqual(len(job.result_json["pipeline_steps"]), 5)
        self.assertEqual(job.result_json["artifacts"]["xlsx_files"], ["/tmp/a.xlsx"])
        self.assertEqual(job.result_json["artifacts"]["docx_files"], ["/tmp/a.docx"])
        self.assertEqual(job.result_json["artifacts"]["pdf_files"], ["/tmp/a.pdf"])
        self.assertTrue(JobLog.objects.filter(job_run=job, message="step_started").exists())
        self.assertTrue(JobLog.objects.filter(job_run=job, message="step_success").exists())

    @patch("pipeline.full_pipeline_runner.run_download_descriptors_step")
    def test_run_full_pipeline_fails_when_download_empty(self, mocked_download):
        mocked_download.return_value = {
            "downloads_total": 1,
            "downloads_success": 0,
            "downloads_failed": 1,
            "files": [{"status": "failed", "error": "403"}],
        }

        job = run_full_pipeline()

        self.assertEqual(job.status, JobRun.Status.FAILED)
        self.assertEqual(job.result_json["summary"]["steps_failed"], 1)
        self.assertEqual(len(job.result_json["pipeline_steps"]), 1)
        self.assertTrue(JobLog.objects.filter(job_run=job, message="step_failed").exists())


class ResolveContactsTests(TestCase):
    def test_resolve_contacts_prefers_db(self):
        ParentContact.objects.create(
            parallel=3,
            class_code="3A",
            student_name="Иван Иванов",
            parent_email_1="p1@example.com",
            parent_email_2="",
            is_active=True,
        )

        contacts = _resolve_contacts()

        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["student"], "Иван Иванов")
        self.assertEqual(contacts[0]["recipients"][0]["value"], "p1@example.com")