import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from jobs.models import JobLog, JobRun
from journal_links.models import ClassSheetLink
from pipeline.services_download import DescriptorDownloadError, run_download_descriptors_step


class DownloadDescriptorsStepTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.link = ClassSheetLink.objects.create(
            class_code="5A",
            subject_name="Math",
            teacher_name="Teacher",
            google_sheet_url="https://docs.google.com/spreadsheets/d/abc123/edit#gid=0",
            is_active=True,
        )

    def test_step_downloads_file_and_returns_summary(self):
        with patch("pipeline.services_download._download_bytes", return_value=b"xlsx-data"):
            result = run_download_descriptors_step(links=[self.link])

        self.assertEqual(result["downloads_total"], 1)
        self.assertEqual(result["downloads_success"], 1)
        self.assertEqual(result["downloads_failed"], 0)
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(result["files"][0]["status"], "success")

        path = Path(result["files"][0]["path"])
        self.assertTrue(path.exists())
        self.assertEqual(path.read_bytes(), b"xlsx-data")
        path.unlink(missing_ok=True)

    def test_step_logs_download_error_without_silent_failure(self):
        job_run = JobRun.objects.create(job_type="download_descriptors", status=JobRun.Status.RUNNING)

        with patch("pipeline.services_download._download_bytes", side_effect=DescriptorDownloadError("401", "401 unauthorized")), patch(
            "pipeline.services_download._download_public_link", side_effect=DescriptorDownloadError("403", "fallback failed")
        ):
            result = run_download_descriptors_step(links=[self.link], job_run=job_run)

        self.assertEqual(result["downloads_failed"], 1)
        self.assertEqual(result["files"][0]["status"], "failed")
        self.assertTrue(JobLog.objects.filter(job_run=job_run, level=JobLog.Level.ERROR).exists())