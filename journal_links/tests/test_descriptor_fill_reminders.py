from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from jobs.models import JobLog, JobRun
from notifications.descriptor_fill_reminders import JOB_TYPE, send_descriptor_fill_reminders
from notifications.models import NotificationEvent, TeacherContact
from notifications.services import TelegramSendError
from validation.descriptor_criteria_fill import JOB_TYPE as FILL_CHECK_JOB_TYPE


class DescriptorFillReminderTests(TestCase):
    def setUp(self):
        self.sheet_url = "https://docs.google.com/spreadsheets/d/fill-source/edit#gid=10"
        self.source_job = self._create_source_job()
        self.user = User.objects.create_user(username="sender", password="p", is_staff=True)
        jobrun_ct = ContentType.objects.get_for_model(JobRun)
        self.view_perm = Permission.objects.get(codename="view_jobrun", content_type=jobrun_ct)
        self.send_perm = Permission.objects.get(codename="send_reminders", content_type=jobrun_ct)
        self.user.user_permissions.add(self.view_perm)
        self.client.force_login(self.user)

    def _create_source_job(self, *, rows=None):
        rows = rows if rows is not None else self._rows()
        return JobRun.objects.create(
            job_type=FILL_CHECK_JOB_TYPE,
            status=JobRun.Status.SUCCESS,
            started_at=timezone.now(),
            finished_at=timezone.now(),
            params_json={"trigger": "scheduled"},
            result_json={
                "summary": {"classes_checked": 3, "subjects_checked": len(rows), "with_problems": 4},
                "rows": rows,
                "tables": [],
            },
        )

    def _rows(self):
        return [
            {
                "teacher_name": "Teacher A",
                "class_code": "7A",
                "subject_name": "Math",
                "module_number": 1,
                "descriptor_status": "missing",
                "criteria_status": "filled",
                "grades_status": "ok",
                "grades_missing": 0,
                "grades_ratio": "4/4",
                "sheet_url": self.sheet_url,
            },
            {
                "teacher_name": "Teacher A",
                "class_code": "7A",
                "subject_name": "English",
                "module_number": 2,
                "descriptor_status": "filled",
                "criteria_status": "filled",
                "grades_status": "missing",
                "grades_missing": 3,
                "grades_ratio": "1/4",
                "sheet_url": self.sheet_url,
            },
            {
                "teacher_name": "Teacher B",
                "class_code": "7B",
                "subject_name": "Science",
                "module_number": 3,
                "descriptor_status": "filled",
                "criteria_status": "missing",
                "grades_status": "ok",
                "grades_missing": 0,
                "grades_ratio": "6/6",
                "sheet_url": self.sheet_url,
            },
            {
                "teacher_name": "",
                "class_code": "7C",
                "subject_name": "History",
                "module_number": 4,
                "descriptor_status": "missing",
                "criteria_status": "filled",
                "grades_status": "ok",
                "grades_missing": 0,
                "grades_ratio": "2/2",
                "sheet_url": self.sheet_url,
            },
            {
                "teacher_name": "Teacher C",
                "class_code": "7D",
                "subject_name": "Art",
                "module_number": 5,
                "descriptor_status": "filled",
                "criteria_status": "filled",
                "grades_status": "not_applicable",
                "grades_missing": 0,
                "grades_ratio": "—",
                "sheet_url": self.sheet_url,
            },
        ]

    def _report_url(self):
        return reverse("journal_links:descriptor_criteria_fill_report")

    def _send_url(self, job_run=None):
        job_run = job_run or self.source_job
        return reverse("journal_links:send_descriptor_criteria_fill_reminders", args=[job_run.id])

    def test_button_visible_for_user_with_send_reminders_permission(self):
        self.user.user_permissions.add(self.send_perm)

        response = self.client.get(self._report_url(), {"run_id": str(self.source_job.id)})

        self.assertContains(response, "Отправить напоминания преподавателям")

    def test_button_hidden_without_send_reminders_permission(self):
        response = self.client.get(self._report_url(), {"run_id": str(self.source_job.id)})

        self.assertNotContains(response, "Отправить напоминания преподавателям")

    def test_send_requires_send_reminders_permission(self):
        response = self.client.post(self._send_url())

        self.assertEqual(response.status_code, 403)

    @patch("notifications.descriptor_fill_reminders.send_telegram")
    def test_send_builds_from_selected_descriptor_fill_jobrun(self, send_telegram_mock):
        self.user.user_permissions.add(self.send_perm)
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        response = self.client.post(self._send_url())

        self.assertEqual(response.status_code, 302)
        reminder_job = JobRun.objects.get(job_type=JOB_TYPE)
        self.assertEqual(response.url, reverse("job_run_detail", kwargs={"run_id": reminder_job.id}))
        self.assertEqual(reminder_job.params_json["source_job_run_id"], str(self.source_job.id))
        self.assertEqual(reminder_job.params_json["trigger"], "manual")
        self.assertEqual(reminder_job.result_json["summary"]["teachers_total"], 2)
        self.assertEqual(reminder_job.result_json["summary"]["sent"], 1)
        self.assertEqual(reminder_job.result_json["summary"]["skipped_no_contact"], 1)
        self.assertEqual(reminder_job.result_json["summary"]["skipped_no_teacher"], 1)
        self.assertEqual(JobRun.objects.filter(job_type=FILL_CHECK_JOB_TYPE).count(), 1)
        send_telegram_mock.assert_called_once()

    @patch("notifications.descriptor_fill_reminders.send_telegram")
    def test_teacher_receives_only_own_problems_with_separate_sections(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)
        TeacherContact.objects.create(name="Teacher B", chat_id="222", is_active=True)

        send_descriptor_fill_reminders(self.source_job)

        self.assertEqual(send_telegram_mock.call_count, 2)
        messages = {call.args[0]: call.args[1] for call in send_telegram_mock.call_args_list}
        self.assertIn("Здравствуйте, Teacher A.", messages["111"])
        self.assertIn("Дескрипторы:", messages["111"])
        self.assertIn("7A, Math, модуль 1", messages["111"])
        self.assertIn("Оценки:", messages["111"])
        self.assertIn("7A, English, модуль 2", messages["111"])
        self.assertNotIn("Science", messages["111"])
        self.assertIn("Здравствуйте, Teacher B.", messages["222"])
        self.assertIn("Критерии:", messages["222"])
        self.assertIn("7B, Science, модуль 3", messages["222"])
        self.assertNotIn("English", messages["222"])
        self.assertIn(self.sheet_url, messages["111"])

    @patch("notifications.descriptor_fill_reminders.send_telegram")
    def test_teacher_without_contact_is_skipped(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        reminder_job = send_descriptor_fill_reminders(self.source_job)

        self.assertEqual(reminder_job.result_json["summary"]["skipped_no_contact"], 1)
        skipped_event = NotificationEvent.objects.get(teacher_name="Teacher B")
        self.assertEqual(skipped_event.status, NotificationEvent.Status.SKIPPED)
        send_telegram_mock.assert_called_once()

    @patch("notifications.descriptor_fill_reminders.send_telegram")
    def test_inactive_contact_is_skipped(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)
        TeacherContact.objects.create(name="Teacher B", chat_id="222", is_active=False)

        reminder_job = send_descriptor_fill_reminders(self.source_job)

        self.assertEqual(reminder_job.result_json["summary"]["skipped_no_contact"], 1)
        self.assertEqual(send_telegram_mock.call_count, 1)

    @patch("notifications.descriptor_fill_reminders.send_telegram")
    def test_duplicate_payload_is_not_sent_twice_for_same_source_jobrun(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        first_job = send_descriptor_fill_reminders(self.source_job)
        second_job = send_descriptor_fill_reminders(self.source_job)

        self.assertEqual(first_job.result_json["summary"]["sent"], 1)
        self.assertEqual(second_job.result_json["summary"]["sent"], 0)
        self.assertEqual(second_job.result_json["summary"]["skipped_duplicate"], 1)
        send_telegram_mock.assert_called_once()

    @patch("notifications.descriptor_fill_reminders.send_telegram")
    def test_notification_events_and_logs_are_created(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        reminder_job = send_descriptor_fill_reminders(self.source_job)

        self.assertTrue(NotificationEvent.objects.filter(job_run=reminder_job, teacher_name="Teacher A").exists())
        self.assertTrue(NotificationEvent.objects.filter(job_run=reminder_job, teacher_name="Teacher B").exists())
        self.assertTrue(JobLog.objects.filter(job_run=reminder_job, message="Descriptor fill reminders started").exists())
        self.assertTrue(JobLog.objects.filter(job_run=reminder_job, message="Reminder sent").exists())
        self.assertTrue(JobLog.objects.filter(job_run=reminder_job, message="Reminder skipped: no contact").exists())
        self.assertTrue(JobLog.objects.filter(job_run=reminder_job, message="Descriptor fill reminders finished").exists())
        send_telegram_mock.assert_called_once()

    @patch("notifications.descriptor_fill_reminders.send_telegram")
    def test_telegram_error_does_not_break_all_distribution(self, send_telegram_mock):
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)
        TeacherContact.objects.create(name="Teacher B", chat_id="222", is_active=True)

        def send_side_effect(chat_id, *_args, **_kwargs):
            if chat_id == "111":
                raise TelegramSendError("boom")
            return {"ok": True}

        send_telegram_mock.side_effect = send_side_effect

        reminder_job = send_descriptor_fill_reminders(self.source_job)

        self.assertEqual(reminder_job.status, JobRun.Status.PARTIAL)
        self.assertEqual(reminder_job.result_json["summary"]["failed"], 1)
        self.assertEqual(reminder_job.result_json["summary"]["sent"], 1)
        error_event = NotificationEvent.objects.get(job_run=reminder_job, teacher_name="Teacher A")
        self.assertEqual(error_event.status, NotificationEvent.Status.ERROR)
        self.assertIn("boom", error_event.error_message)
        self.assertTrue(JobLog.objects.filter(job_run=reminder_job, message="Reminder failed").exists())

    @patch("journal_links.views.enqueue_descriptor_criteria_fill_check_job")
    @patch("notifications.descriptor_fill_reminders.send_telegram")
    def test_send_does_not_start_new_check_or_ai(self, send_telegram_mock, enqueue_mock):
        self.user.user_permissions.add(self.send_perm)
        TeacherContact.objects.create(name="Teacher A", chat_id="111", is_active=True)

        response = self.client.post(self._send_url())

        self.assertEqual(response.status_code, 302)
        enqueue_mock.assert_not_called()
        self.assertEqual(JobRun.objects.filter(job_type=FILL_CHECK_JOB_TYPE).count(), 1)
        self.assertEqual(JobRun.objects.filter(job_type=JOB_TYPE).count(), 1)
        send_telegram_mock.assert_called_once()
