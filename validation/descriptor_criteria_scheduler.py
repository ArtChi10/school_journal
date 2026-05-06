from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta

from django.utils import timezone

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from journal_links.models import DescriptorCriteriaCheckSchedule
from validation.descriptor_criteria_fill import JOB_TYPE, run_descriptor_criteria_fill_check_job

logger = logging.getLogger(__name__)

SCHEDULER_POLL_SECONDS = 60
OVERLAP_RETRY_MINUTES = 5
ACTIVE_JOB_STATUSES = [JobRun.Status.PENDING, JobRun.Status.RUNNING]


DescriptorCriteriaRunner = Callable[..., JobRun]


def _next_run_after(base_time, interval_minutes: int):
    return base_time + timedelta(minutes=interval_minutes)


def _scheduled_params(schedule: DescriptorCriteriaCheckSchedule) -> dict:
    return {
        "class_code": None,
        "all_active": True,
        "trigger": "scheduled",
        "schedule_id": schedule.id,
        "interval_minutes": schedule.interval_minutes,
    }


def _has_active_descriptor_criteria_job() -> bool:
    return JobRun.objects.filter(job_type=JOB_TYPE, status__in=ACTIVE_JOB_STATUSES).exists()


def run_due_descriptor_criteria_schedule(
    *,
    now=None,
    runner: DescriptorCriteriaRunner = run_descriptor_criteria_fill_check_job,
) -> JobRun | None:
    now = now or timezone.now()
    schedule = DescriptorCriteriaCheckSchedule.load()
    logger.info("Scheduler tick")

    if not schedule.is_enabled:
        logger.info("Schedule disabled")
        return None

    if schedule.next_run_at is None:
        schedule.next_run_at = now
        schedule.save(update_fields=["next_run_at", "updated_at"])

    if schedule.next_run_at and schedule.next_run_at > now:
        return None

    if _has_active_descriptor_criteria_job():
        schedule.next_run_at = _next_run_after(now, OVERLAP_RETRY_MINUTES)
        schedule.save(update_fields=["next_run_at", "updated_at"])
        logger.info("Scheduled check skipped: previous run still running")
        return None

    params = _scheduled_params(schedule)
    job_run = JobRun.objects.create(
        job_type=JOB_TYPE,
        status=JobRun.Status.PENDING,
        started_at=now,
        params_json=params,
    )
    schedule.last_started_at = now
    schedule.last_job_run = job_run
    schedule.save(update_fields=["last_started_at", "last_job_run", "updated_at"])

    log_step(
        job_run=job_run,
        level=JobLog.Level.INFO,
        message="Scheduled check started",
        context=params,
    )
    logger.info("Scheduled check started", extra={"job_run_id": str(job_run.id)})

    try:
        job_run = runner(
            class_code=None,
            all_active=True,
            job_run=job_run,
            trigger="scheduled",
            schedule_id=schedule.id,
            interval_minutes=schedule.interval_minutes,
        )
    except Exception as exc:  # noqa: BLE001
        job_run.status = JobRun.Status.FAILED
        job_run.finished_at = timezone.now()
        job_run.result_json = {
            "summary": {},
            "rows": [],
            "tables": [],
            "error": str(exc),
            "report": {"status": "skipped", "reason": "scheduler_runner_failed"},
        }
        job_run.save(update_fields=["status", "finished_at", "result_json"])
        log_step(
            job_run=job_run,
            level=JobLog.Level.ERROR,
            message="Scheduled check failed",
            context={"reason": str(exc), **params},
        )
        logger.exception("Scheduled check failed", extra={"job_run_id": str(job_run.id)})
    else:
        if job_run.status == JobRun.Status.FAILED:
            message = "Scheduled check failed"
            level = JobLog.Level.ERROR
        else:
            message = "Scheduled check finished"
            level = JobLog.Level.INFO
        log_step(
            job_run=job_run,
            level=level,
            message=message,
            context={"status": job_run.status, **params},
        )
        logger.info(message, extra={"job_run_id": str(job_run.id), "status": job_run.status})

    schedule.last_finished_at = job_run.finished_at or timezone.now()
    schedule.next_run_at = _next_run_after(schedule.last_finished_at, schedule.interval_minutes)
    schedule.last_job_run = job_run
    schedule.save(update_fields=["last_finished_at", "next_run_at", "last_job_run", "updated_at"])
    return job_run
