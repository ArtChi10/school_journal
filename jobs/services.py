from typing import Any

from jobs.models import JobLog, JobRun


def log_step(
    job_run: JobRun,
    level: str,
    message: str,
    context: dict[str, Any] | None = None,
) -> JobLog:
    return JobLog.objects.create(
        job_run=job_run,
        level=level,
        message=message,
        context_json=context or {},
    )