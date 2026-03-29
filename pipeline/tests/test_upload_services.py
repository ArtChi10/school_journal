import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from jobs.models import JobLog
from pipeline.docx_job_runner import run_generate_docx_job
from pipeline.services_upload import ReviewUploadError, resolve_review_folder_id, run_upload_docx_review_step


class ResolveReviewFolderTests(SimpleTestCase):
    @patch.dict("os.environ", {"GOOGLE_REVIEW_FOLDER_MAP": "4A:folder_1,5B:folder_2"}, clear=True)
    def test_resolve_folder_from_mapping(self):
        self.assertEqual(resolve_review_folder_id("4A"), "folder_1")

    @patch.dict("os.environ", {"GOOGLE_REVIEW_FOLDER_ID": "default_folder"}, clear=True)
    def test_resolve_folder_from_default(self):
        self.assertEqual(resolve_review_folder_id("9C"), "default_folder")

    @patch.dict("os.environ", {}, clear=True)
    def test_raises_without_config(self):
        with self.assertRaises(ReviewUploadError):
            resolve_review_folder_id("4A")


class UploadReviewStepTests(SimpleTestCase):
    @patch.dict(
        "os.environ",
        {
            "GOOGLE_REVIEW_FOLDER_ID": "folder_main",
            "GOOGLE_REVIEW_DUPLICATE_STRATEGY": "update",
        },
        clear=True,
    )
    @patch("pipeline.services_upload._build_drive_service", return_value=object())
    @patch("pipeline.services_upload._upload_or_update_file", return_value=("file123", "https://drive/link"))
    def test_upload_review_step_success(self, _mock_upload, _mock_service):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "4A" / "John Doe.docx"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"docx")

            result = run_upload_docx_review_step(docx_files=[str(path)])

        self.assertEqual(result["uploaded_total"], 1)
        self.assertEqual(result["uploaded_success"], 1)
        self.assertEqual(result["uploaded_failed"], 0)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["uploaded_files"][0]["class_code"], "4A")
        self.assertEqual(result["uploaded_files"][0]["drive_file_id"], "file123")

    @patch.dict(
        "os.environ",
        {
            "GOOGLE_REVIEW_FOLDER_ID": "folder_main",
            "GOOGLE_REVIEW_DUPLICATE_STRATEGY": "skip",
        },
        clear=True,
    )
    @patch("pipeline.services_upload._build_drive_service", return_value=object())
    @patch("pipeline.services_upload._upload_or_update_file", side_effect=FileNotFoundError("not found"))
    def test_upload_review_step_collects_errors(self, _mock_upload, _mock_service):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "4A" / "John Doe.docx"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"docx")

            result = run_upload_docx_review_step(docx_files=[{"path": str(path), "class_code": "4A"}])

        self.assertEqual(result["uploaded_total"], 1)
        self.assertEqual(result["uploaded_success"], 0)
        self.assertEqual(result["uploaded_failed"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["type"], "FileNotFoundError")


class GenerateDocxUploadIntegrationTests(TestCase):
    @patch.dict(
        "os.environ",
        {
            "GOOGLE_REVIEW_FOLDER_ID": "folder_main",
            "GOOGLE_REVIEW_DUPLICATE_STRATEGY": "update",
        },
        clear=True,
    )
    @patch("pipeline.docx_job_runner.run_upload_docx_review_step")
    def test_generate_job_includes_upload_result(self, mock_upload_step):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            xlsx = tmp / "journal_4A.xlsx"
            xlsx.write_bytes(b"xlsx")
            out = tmp / "out"

            def _fake_generate(self, workbook_path, output_dir, temp_dir):
                output_dir.mkdir(parents=True, exist_ok=True)
                p = output_dir / "John Doe.docx"
                p.write_bytes(b"docx")
                return [str(p)]

            mock_upload_step.return_value = {
                "uploaded_total": 1,
                "uploaded_success": 1,
                "uploaded_failed": 0,
                "uploaded_files": [
                    {
                        "name": "John Doe.docx",
                        "class_code": "4A",
                        "drive_file_id": "drive_id",
                        "link": "https://drive/link",
                    }
                ],
                "errors": [],
            }

            with patch("pipeline.docx_job_runner.LegacyDocxGenerator.generate_for_workbook", new=_fake_generate):
                job = run_generate_docx_job(
                    xlsx_files=[str(xlsx)],
                    output_root=str(out),
                    upload_to_review=True,
                )

        self.assertEqual(job.result_json["uploaded_total"], 1)
        self.assertEqual(job.result_json["uploaded_success"], 1)
        self.assertEqual(job.result_json["uploaded_failed"], 0)
        self.assertEqual(len(job.result_json["uploaded_files"]), 1)
        self.assertEqual(job.status, "success")
        self.assertTrue(JobLog.objects.filter(job_run=job, message="DOCX generation finished").exists())