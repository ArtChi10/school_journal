from django.test import TestCase
from django.urls import reverse

from jobs.models import JobRun
from notifications.models import TeacherConfirmation


class JobRunDetailViewTests(TestCase):
    def test_detail_shows_teacher_confirmations(self):
        job_run = JobRun.objects.create(job_type="run_validation")
        TeacherConfirmation.objects.create(
            job_run=job_run,
            teacher_name="Teacher A",
            chat_id="100",
            message_text="исправил",
            confirmed_at="2026-03-28T10:00:00Z",
        )

        response = self.client.get(reverse("job_run_detail", kwargs={"run_id": job_run.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Подтверждения учителей")
        self.assertContains(response, "Teacher A")
        self.assertContains(response, "исправил")