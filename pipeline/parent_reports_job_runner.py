from __future__ import annotations

from django.utils import timezone

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from pipeline.services_parent_reports import run_send_parent_reports_step


def run_send_parent_reports_job(
    *,
    pdf_files: list[dict | str],
    contacts: list[dict],
    initiated_by=None,
) -> JobRun:
    params = {
        "pdf_files": pdf_files,
        "contacts_total": len(contacts),
    }
    job_run = JobRun.objects.create(
        job_type="send_parent_reports",
        status=JobRun.Status.RUNNING,
        started_at=timezone.now(),
        params_json=params,
        initiated_by=initiated_by,
    )

    log_step(
        job_run=job_run,
        level=JobLog.Level.INFO,
        message="Parent reports sending started",
        context={"pdf_total": len(pdf_files), "contacts_total": len(contacts)},
    )

    try:
        result = run_send_parent_reports_step(pdf_files=pdf_files, contacts=contacts, job_run=job_run)

        if result["sent_failed"] > 0 and result["sent_success"] > 0:
            final_status = JobRun.Status.PARTIAL
        elif result["sent_failed"] > 0 and result["sent_success"] == 0:
            final_status = JobRun.Status.FAILED
        elif result["sent_success"] > 0:
            final_status = JobRun.Status.SUCCESS
        elif result["skipped_no_contact"] > 0 or result["skipped_no_pdf"] > 0:
            final_status = JobRun.Status.PARTIAL
        else:
            final_status = JobRun.Status.FAILED

        job_run.result_json = result
        job_run.status = final_status
        job_run.finished_at = timezone.now()
        job_run.save(update_fields=["result_json", "status", "finished_at"])

        log_step(
            job_run=job_run,
            level=JobLog.Level.INFO,
            message="Parent reports sending finished",
            context={"status": final_status, **result},
        )
    except Exception as exc:  # noqa: BLE001
        job_run.status = JobRun.Status.FAILED
        job_run.finished_at = timezone.now()
        job_run.save(update_fields=["status", "finished_at"])
        log_step(job_run=job_run, level=JobLog.Level.ERROR, message=f"Parent reports sending failed: {exc}")

    return job_run