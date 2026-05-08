from datetime import timedelta
from unittest.mock import Mock

from django.test import TestCase
from django.utils import timezone

from jobs.models import JobRun
from journal_links.models import DescriptorCriteriaCheckSchedule
from validation.descriptor_criteria_fill import JOB_TYPE
from validation.descriptor_criteria_scheduler import (
    OVERLAP_RETRY_MINUTES,
    run_due_descriptor_criteria_schedule,
)


class DescriptorCriteriaSchedulerTests(TestCase):
    def _successful_runner(self, **kwargs):
        job_run = kwargs["job_run"]
        job_run.status = JobRun.Status.SUCCESS
        job_run.finished_at = timezone.now()
        job_run.result_json = {"summary": {}, "rows": [], "tables": []}
        job_run.save(update_fields=["status", "finished_at", "result_json"])
        return job_run

    def test_disabled_schedule_does_not_start_job(self):
        now = timezone.now()
        schedule = DescriptorCriteriaCheckSchedule.load()
        schedule.is_enabled = False
        schedule.next_run_at = now - timedelta(minutes=1)
        schedule.save()
        runner = Mock()

        result = run_due_descriptor_criteria_schedule(now=now, runner=runner)

        self.assertIsNone(result)
        runner.assert_not_called()
        self.assertFalse(JobRun.objects.filter(job_type=JOB_TYPE).exists())

    def test_enabled_due_schedule_creates_scheduled_job(self):
        now = timezone.now()
        schedule = DescriptorCriteriaCheckSchedule.load()
        schedule.is_enabled = True
        schedule.next_run_at = now - timedelta(minutes=1)
        schedule.save()

        job_run = run_due_descriptor_criteria_schedule(now=now, runner=self._successful_runner)

        self.assertIsNotNone(job_run)
        self.assertEqual(JobRun.objects.filter(job_type=JOB_TYPE).count(), 1)
        self.assertEqual(job_run.params_json["trigger"], "scheduled")
        self.assertEqual(job_run.params_json["schedule_id"], schedule.id)
        self.assertEqual(job_run.params_json["interval_minutes"], 30)
        self.assertTrue(job_run.logs.filter(message="Scheduled check started").exists())
        self.assertTrue(job_run.logs.filter(message="Scheduled check finished").exists())

    def test_running_job_prevents_overlap(self):
        now = timezone.now()
        schedule = DescriptorCriteriaCheckSchedule.load()
        schedule.is_enabled = True
        schedule.next_run_at = now - timedelta(minutes=1)
        schedule.save()
        JobRun.objects.create(job_type=JOB_TYPE, status=JobRun.Status.RUNNING, started_at=now)
        runner = Mock()

        result = run_due_descriptor_criteria_schedule(now=now, runner=runner)

        self.assertIsNone(result)
        runner.assert_not_called()
        self.assertEqual(JobRun.objects.filter(job_type=JOB_TYPE).count(), 1)
        schedule.refresh_from_db()
        self.assertEqual(schedule.next_run_at, now + timedelta(minutes=OVERLAP_RETRY_MINUTES))

    def test_successful_run_updates_schedule_times(self):
        now = timezone.now()
        schedule = DescriptorCriteriaCheckSchedule.load()
        schedule.is_enabled = True
        schedule.next_run_at = now - timedelta(minutes=1)
        schedule.save()

        job_run = run_due_descriptor_criteria_schedule(now=now, runner=self._successful_runner)

        schedule.refresh_from_db()
        self.assertEqual(schedule.last_started_at, now)
        self.assertEqual(schedule.last_job_run, job_run)
        self.assertEqual(schedule.last_finished_at, job_run.finished_at)
        self.assertEqual(schedule.next_run_at, job_run.finished_at + timedelta(minutes=30))
