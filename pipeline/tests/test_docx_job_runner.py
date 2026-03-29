import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from jobs.models import JobLog, JobRun
from pipeline.docx_job_runner import run_generate_docx_job


class GenerateDocxJobRunnerTests(TestCase):
    def test_run_generate_docx_job_partial_mode_and_result_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            ok_xlsx = tmp / "journal_4A.xlsx"
            bad_xlsx = tmp / "journal_5B.xlsx"
            ok_xlsx.write_bytes(b"xlsx content")

            output_root = tmp / "output"

            def _fake_generate(self, workbook_path, output_dir, temp_dir):
                if workbook_path == bad_xlsx:
                    raise RuntimeError("broken workbook")
                output_dir.mkdir(parents=True, exist_ok=True)
                file_path = output_dir / "John Doe.docx"
                file_path.write_bytes(b"docx")
                return [str(file_path)]

            with patch("pipeline.docx_job_runner.LegacyDocxGenerator.generate_for_workbook", new=_fake_generate):
                job = run_generate_docx_job(
                    xlsx_files=[str(ok_xlsx), str(bad_xlsx)],
                    output_root=str(output_root),
                )

        self.assertEqual(job.job_type, "generate_docx_reports")
        self.assertEqual(job.status, JobRun.Status.PARTIAL)

        result = job.result_json
        self.assertEqual(result["docx_total"], 1)
        self.assertEqual(result["docx_success"], 1)
        self.assertEqual(result["docx_failed"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(len(result["files"]), 1)
        self.assertIn("4A", result["output_dirs"][0])
        self.assertIn("5B", result["output_dirs"][1])

        logs = JobLog.objects.filter(job_run=job)
        self.assertTrue(logs.filter(message="DOCX generation started").exists())
        self.assertTrue(logs.filter(message="DOCX generation finished").exists())
        self.assertTrue(logs.filter(message="Class DOCX generation summary").exists())
        self.assertTrue(logs.filter(level=JobLog.Level.ERROR).exists())

    def test_management_command_creates_job(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            xlsx = tmp / "journal_6C.xlsx"
            xlsx.write_bytes(b"xlsx content")
            out_dir = tmp / "docx_out"

            def _fake_generate(self, workbook_path, output_dir, temp_dir):
                output_dir.mkdir(parents=True, exist_ok=True)
                path = output_dir / "Jane Roe.docx"
                path.write_bytes(b"docx")
                return [str(path)]

            with patch("pipeline.docx_job_runner.LegacyDocxGenerator.generate_for_workbook", new=_fake_generate):
                call_command(
                    "generate_docx_reports",
                    "--xlsx",
                    str(xlsx),
                    "--output-root",
                    str(out_dir),
                )

        self.assertTrue(JobRun.objects.filter(job_type="generate_docx_reports").exists())
