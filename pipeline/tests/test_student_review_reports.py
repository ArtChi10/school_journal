import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from jobs.models import JobLog, JobRun
from journal_links.models import ClassSheetLink
from pipeline.services_upload import _upload_or_update_file_with_action, upload_docx_files_to_drive_folder
from pipeline.student_review_reports import JOB_TYPE, run_prepare_student_review_reports_job


def _sheet_url(sheet_id="sheet"):
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


def _drive_folder_url(folder_id="folder123456789"):
    return f"https://drive.google.com/drive/folders/{folder_id}"


class StudentReviewReportsViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="admin", password="p")
        perms = Permission.objects.filter(codename__in=["view_jobrun", "run_full_pipeline"])
        self.user.user_permissions.add(*perms)
        self.client.force_login(self.user)

    def test_page_shows_only_active_classes(self):
        ClassSheetLink.objects.create(
            class_code="4A",
            subject_name="Math",
            google_sheet_url=_sheet_url("active"),
            is_active=True,
        )
        ClassSheetLink.objects.create(
            class_code="5B",
            subject_name="History",
            google_sheet_url=_sheet_url("inactive"),
            is_active=False,
        )

        response = self.client.get(reverse("pipeline:student_review_reports"))

        self.assertEqual(response.status_code, 200)
        page = response.content.decode("utf-8")
        self.assertIn("Отчеты на проверку", page)
        self.assertIn("4A", page)
        self.assertNotIn("5B", page)

    @patch("pipeline.views.enqueue_prepare_student_review_reports_job")
    def test_manual_post_creates_job_with_selected_params(self, mock_enqueue):
        link = ClassSheetLink.objects.create(
            class_code="4A",
            subject_name="Math",
            google_sheet_url=_sheet_url("active"),
            is_active=True,
        )
        job_run = JobRun.objects.create(job_type=JOB_TYPE, status=JobRun.Status.PENDING)
        mock_enqueue.return_value = job_run

        response = self.client.post(
            reverse("pipeline:student_review_reports"),
            {
                "class_sheet_link": link.id,
                "drive_folder_url": _drive_folder_url("folder123456789"),
                "module_number": "2",
                "module_dates": "1 сентября - 25 октября",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(str(job_run.id), response["Location"])
        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args.kwargs
        self.assertEqual(kwargs["class_sheet_link_id"], link.id)
        self.assertEqual(kwargs["drive_folder_url"], _drive_folder_url("folder123456789"))
        self.assertEqual(kwargs["module_number"], 2)
        self.assertEqual(kwargs["module_dates"], "1 сентября - 25 октября")
        self.assertEqual(kwargs["initiated_by"], self.user)


class FakeDocxGenerator:
    def __init__(self, capture):
        self.capture = capture

    def generate_for_workbook(
        self,
        *,
        workbook_path,
        output_dir,
        temp_dir,
        module_number,
        module_dates,
        school_level,
        include_tutor,
    ):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        self.capture.update(
            {
                "workbook_path": str(workbook_path),
                "output_dir": str(output_dir),
                "temp_dir": str(temp_dir),
                "module_number": module_number,
                "module_dates": module_dates,
                "school_level": school_level,
                "include_tutor": include_tutor,
            }
        )
        docx_path = output_dir / "John Doe.docx"
        docx_path.write_bytes(b"docx")
        return [str(docx_path)]


class StudentReviewReportsJobTests(TestCase):
    def _link(self, class_code="4A"):
        return ClassSheetLink.objects.create(
            class_code=class_code,
            subject_name="Math",
            google_sheet_url=_sheet_url(class_code),
            is_active=True,
        )

    def _run_job(self, *, class_code="4A"):
        link = self._link(class_code)
        capture = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = Path(tmpdir) / "journal.xlsx"
            workbook.write_bytes(b"xlsx")
            with (
                patch("pipeline.student_review_reports.fetch_workbook_for_link", return_value=workbook),
                patch("pipeline.student_review_reports.upload_docx_files_to_drive_folder") as mock_upload,
            ):
                mock_upload.return_value = {
                    "uploaded_total": 1,
                    "uploaded_success": 1,
                    "uploaded_failed": 0,
                    "uploaded_created": 0,
                    "uploaded_updated": 1,
                    "uploaded_skipped": 0,
                    "uploaded_files": [
                        {
                            "name": f"{class_code} John Doe.docx",
                            "class_code": class_code,
                            "drive_file_id": "drive-id",
                            "link": "https://drive.google.com/file/d/drive-id/view",
                            "action": "updated",
                        }
                    ],
                    "errors": [],
                }
                job = run_prepare_student_review_reports_job(
                    class_sheet_link_id=link.id,
                    drive_folder_url=_drive_folder_url("folder123456789"),
                    module_number=2,
                    module_dates="1 сентября - 25 октября",
                    generator=FakeDocxGenerator(capture),
                )
                upload_kwargs = mock_upload.call_args.kwargs
                output_dir = Path(capture["output_dir"])

        return job, capture, upload_kwargs, output_dir

    def test_run_creates_job_params_result_logs_and_removes_temp_files(self):
        job, capture, upload_kwargs, output_dir = self._run_job(class_code="4A")

        self.assertEqual(job.job_type, JOB_TYPE)
        self.assertEqual(job.status, JobRun.Status.SUCCESS)
        self.assertEqual(job.params_json["class_code"], "4A")
        self.assertEqual(job.params_json["drive_folder_id"], "folder123456789")
        self.assertEqual(job.params_json["module_number"], 2)
        self.assertEqual(job.params_json["module_dates"], "1 сентября - 25 октября")
        self.assertEqual(job.params_json["output_format"], "docx")
        self.assertEqual(job.params_json["trigger"], "manual")
        self.assertEqual(job.result_json["summary"]["students_found"], 1)
        self.assertEqual(job.result_json["summary"]["docx_created"], 1)
        self.assertEqual(job.result_json["summary"]["uploaded_updated"], 1)
        self.assertTrue(job.result_json["local_temp_removed"])
        self.assertFalse(output_dir.exists())
        self.assertEqual(capture["module_number"], 2)
        self.assertEqual(capture["module_dates"], "1 сентября - 25 октября")
        self.assertEqual(upload_kwargs["folder_id"], "folder123456789")
        self.assertEqual(upload_kwargs["duplicate_strategy"], "update")
        self.assertEqual(upload_kwargs["docx_files"][0]["name"], "4A John Doe.docx")
        self.assertTrue(JobLog.objects.filter(job_run=job, message="Student review DOCX reports started").exists())
        self.assertTrue(JobLog.objects.filter(job_run=job, message="DOCX created for student").exists())
        self.assertTrue(JobLog.objects.filter(job_run=job, message="Local temporary DOCX files removed").exists())

    def test_primary_classes_use_primary_scale_and_skip_tutor(self):
        job, capture, _upload_kwargs, _output_dir = self._run_job(class_code="3A")

        self.assertEqual(job.result_json["school_level"], "primary")
        self.assertFalse(job.result_json["include_tutor"])
        self.assertEqual(capture["school_level"], "primary")
        self.assertFalse(capture["include_tutor"])

    def test_secondary_classes_use_secondary_scale_and_include_tutor(self):
        job, capture, _upload_kwargs, _output_dir = self._run_job(class_code="4A")

        self.assertEqual(job.result_json["school_level"], "secondary")
        self.assertTrue(job.result_json["include_tutor"])
        self.assertEqual(capture["school_level"], "secondary")
        self.assertTrue(capture["include_tutor"])


class StudentReviewReportsUploadTests(SimpleTestCase):
    @patch("pipeline.services_upload._build_drive_service", return_value=object())
    @patch("pipeline.services_upload._upload_or_update_file_with_action", return_value=("drive-id", "https://drive/file", "updated"))
    def test_upload_summary_counts_updated_existing_files(self, mock_upload, _mock_service):
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "4A John Doe.docx"
            docx_path.write_bytes(b"docx")

            result = upload_docx_files_to_drive_folder(
                docx_files=[{"path": str(docx_path), "name": docx_path.name, "class_code": "4A"}],
                folder_id="folder123456789",
                duplicate_strategy="update",
            )

        self.assertEqual(result["uploaded_success"], 1)
        self.assertEqual(result["uploaded_updated"], 1)
        self.assertEqual(result["uploaded_created"], 0)
        self.assertEqual(result["uploaded_files"][0]["action"], "updated")
        mock_upload.assert_called_once()

    @patch("googleapiclient.http.MediaFileUpload", return_value=object())
    @patch("pipeline.services_upload._find_existing_file", return_value={"id": "existing-id", "webViewLink": "https://drive/old"})
    def test_drive_helper_updates_existing_file_in_folder(self, _mock_find, _mock_media):
        class _Execute:
            def __init__(self, payload):
                self.payload = payload

            def execute(self):
                return self.payload

        class _Files:
            def __init__(self):
                self.updated = False

            def update(self, **_kwargs):
                self.updated = True
                return _Execute({"id": "existing-id", "webViewLink": "https://drive/new"})

            def create(self, **_kwargs):
                raise AssertionError("create must not be called for an existing DOCX")

        class _Service:
            def __init__(self):
                self.files_resource = _Files()

            def files(self):
                return self.files_resource

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "4A John Doe.docx"
            docx_path.write_bytes(b"docx")
            service = _Service()

            file_id, link, action = _upload_or_update_file_with_action(
                service,
                local_path=docx_path,
                folder_id="folder123456789",
                duplicate_strategy="update",
            )

        self.assertEqual(file_id, "existing-id")
        self.assertEqual(link, "https://drive/new")
        self.assertEqual(action, "updated")
        self.assertTrue(service.files_resource.updated)
