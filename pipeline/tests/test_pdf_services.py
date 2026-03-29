import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from jobs.models import JobLog, JobRun
from pipeline.services_pdf import run_convert_docx_to_pdf_step


class PdfConversionServicesTests(SimpleTestCase):
    @patch("pipeline.services_pdf._convert_docx_local")
    def test_local_mode_converts_and_splits_by_class(self, mock_local_convert):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            docx = base / "output" / "4A" / "John Doe.docx"
            docx.parent.mkdir(parents=True, exist_ok=True)
            docx.write_bytes(b"docx")

            def _fake_local(docx_path, pdf_path):
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                pdf_path.write_bytes(b"pdf")

            mock_local_convert.side_effect = _fake_local
            with patch.dict("os.environ", {"PDF_CONVERT_MODE": "local", "PDF_OUTPUT_ROOT": str(base / "output" / "pdf")}, clear=True):
                result = run_convert_docx_to_pdf_step(docx_files=[str(docx)])

            out_pdf = base / "output" / "pdf" / "4A" / "John Doe.pdf"
            self.assertEqual(result["pdf_total"], 1)
            self.assertEqual(result["pdf_success"], 1)
            self.assertEqual(result["pdf_failed"], 0)
            self.assertTrue(out_pdf.exists())
            self.assertEqual(result["pdf_files"][0]["class_code"], "4A")

    @patch("pipeline.services_pdf._convert_docx_google")
    @patch("pipeline.services_pdf._convert_docx_local", side_effect=RuntimeError("libreoffice missing"))
    def test_local_mode_fallbacks_to_google(self, _mock_local, mock_google):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            docx = base / "output" / "5B" / "Jane Roe.docx"
            docx.parent.mkdir(parents=True, exist_ok=True)
            docx.write_bytes(b"docx")

            def _fake_google(docx_path, pdf_path):
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                pdf_path.write_bytes(b"pdf")

            mock_google.side_effect = _fake_google
            with patch.dict("os.environ", {"PDF_CONVERT_MODE": "local", "PDF_OUTPUT_ROOT": str(base / "output" / "pdf")}, clear=True):
                result = run_convert_docx_to_pdf_step(docx_files=[str(docx)])

            self.assertEqual(result["pdf_success"], 1)
            self.assertEqual(result["pdf_failed"], 0)
            self.assertEqual(result["errors"], [])

    @patch("pipeline.services_pdf._convert_docx_google", side_effect=RuntimeError("oauth broken"))
    def test_google_mode_returns_clear_error(self, _mock_google):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            docx = base / "output" / "6C" / "Alex.docx"
            docx.parent.mkdir(parents=True, exist_ok=True)
            docx.write_bytes(b"docx")

            with patch.dict("os.environ", {"PDF_CONVERT_MODE": "google", "PDF_OUTPUT_ROOT": str(base / "output" / "pdf")}, clear=True):
                result = run_convert_docx_to_pdf_step(docx_files=[str(docx)])

            self.assertEqual(result["pdf_success"], 0)
            self.assertEqual(result["pdf_failed"], 1)
            self.assertEqual(len(result["errors"]), 1)
            self.assertEqual(result["errors"][0]["mode"], "google")


class PdfConversionLoggingTests(TestCase):
    @patch.dict("os.environ", {"PDF_CONVERT_MODE": "local", "PDF_OUTPUT_ROOT": "output/pdf"}, clear=True)
    @patch("pipeline.services_pdf._convert_docx_local")
    def test_logs_mode_input_output_for_each_file(self, mock_local_convert):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            docx = base / "output" / "7D" / "Student Name.docx"
            docx.parent.mkdir(parents=True, exist_ok=True)
            docx.write_bytes(b"docx")

            def _fake_local(docx_path, pdf_path):
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                pdf_path.write_bytes(b"pdf")

            mock_local_convert.side_effect = _fake_local

            job = JobRun.objects.create(job_type="convert_docx_to_pdf", status=JobRun.Status.RUNNING)
            result = run_convert_docx_to_pdf_step(docx_files=[str(docx)], job_run=job)

        self.assertEqual(result["pdf_success"], 1)
        log = JobLog.objects.filter(job_run=job, message="DOCX converted to PDF").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.context_json["mode"], "local")
        self.assertTrue(log.context_json["docx_input"].endswith("Student Name.docx"))
        self.assertTrue(log.context_json["pdf_output"].endswith("Student Name.pdf"))