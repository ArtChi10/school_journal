from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from django.utils import timezone

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from pipeline.docx_job_runner import run_generate_docx_job
from pipeline.job_runner import run_build_criteria_job
from pipeline.parent_reports_job_runner import run_send_parent_reports_job
from pipeline.services_download import run_download_descriptors_step
from pipeline.services_pdf import run_convert_docx_to_pdf_step
from pipeline.parent_contacts import parent_contacts_to_pipeline_payload


PIPELINE_JOB_TYPE = "run_full_pipeline"


class StopPipeline(Exception):
    pass


def _step_started(job_run: JobRun, step_key: str, title: str, context: dict[str, Any] | None = None) -> None:
    log_step(
        job_run=job_run,
        level=JobLog.Level.INFO,
        message="step_started",
        context={"step": step_key, "title": title, **(context or {})},
    )


def _step_success(job_run: JobRun, step_key: str, title: str, context: dict[str, Any] | None = None) -> None:
    log_step(
        job_run=job_run,
        level=JobLog.Level.INFO,
        message="step_success",
        context={"step": step_key, "title": title, **(context or {})},
    )


def _step_failed(job_run: JobRun, step_key: str, title: str, reason: str, context: dict[str, Any] | None = None) -> None:
    log_step(
        job_run=job_run,
        level=JobLog.Level.ERROR,
        message="step_failed",
        context={"step": step_key, "title": title, "reason": reason, **(context or {})},
    )


def _resolve_contacts() -> list[dict]:
    contacts_from_db = parent_contacts_to_pipeline_payload()
    if contacts_from_db:
        return contacts_from_db
    contacts_json = (os.getenv("PARENT_REPORTS_CONTACTS_JSON") or "").strip()
    contacts_csv = (os.getenv("PARENT_REPORTS_CONTACTS_CSV") or "").strip()

    if contacts_json:
        path = Path(contacts_json)
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return payload

    if contacts_csv:
        path = Path(contacts_csv)
        if path.exists():
            contacts: list[dict] = []
            with path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    contacts.append(
                        {
                            "class_code": (row.get("class_code") or "").strip(),
                            "student": (row.get("student") or "").strip(),
                            "recipients": [{"channel": "email", "value": (row.get("email") or "").strip()}],
                        }
                    )
            return contacts

    return []


def run_full_pipeline(*, initiated_by=None) -> JobRun:
    job_run = JobRun.objects.create(
        job_type=PIPELINE_JOB_TYPE,
        status=JobRun.Status.RUNNING,
        started_at=timezone.now(),
        params_json={},
        initiated_by=initiated_by,
    )

    pipeline_steps: list[dict[str, Any]] = []
    artifacts: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []

    try:
        # TASK-021: Download descriptors
        step = {"key": "TASK-021", "title": "Download descriptors", "status": "running"}
        pipeline_steps.append(step)
        _step_started(job_run, step["key"], step["title"])

        download_result = run_download_descriptors_step(job_run=job_run)
        xlsx_files = [item["path"] for item in download_result.get("files", []) if item.get("status") == "success"]
        artifacts["xlsx_files"] = xlsx_files
        step["summary"] = {
            "downloads_total": download_result.get("downloads_total", 0),
            "downloads_success": download_result.get("downloads_success", 0),
            "downloads_failed": download_result.get("downloads_failed", 0),
        }

        if download_result.get("downloads_success", 0) == 0:
            step["status"] = "failed"
            errors.append({"step": step["key"], "reason": "No descriptors downloaded"})
            _step_failed(job_run, step["key"], step["title"], "No descriptors downloaded", step["summary"])
            raise StopPipeline()

        step["status"] = "partial" if download_result.get("downloads_failed", 0) > 0 else "success"
        _step_success(job_run, step["key"], step["title"], {"status": step["status"], **step["summary"]})

        # TASK-022: Build criteria table
        step = {"key": "TASK-022", "title": "Build criteria table", "status": "running"}
        pipeline_steps.append(step)
        _step_started(job_run, step["key"], step["title"])

        criteria_job = run_build_criteria_job(all_active=True, initiated_by=initiated_by)
        step["job_run_id"] = str(criteria_job.id)
        step["summary"] = (criteria_job.result_json or {}).get("summary", {})
        step["status"] = criteria_job.status
        if criteria_job.status == JobRun.Status.FAILED:
            reason = "Criteria build failed"
            errors.append({"step": step["key"], "reason": reason, "job_run_id": str(criteria_job.id)})
            _step_failed(job_run, step["key"], step["title"], reason, {"job_run_id": str(criteria_job.id)})
        else:
            _step_success(job_run, step["key"], step["title"], {"status": step["status"], "job_run_id": str(criteria_job.id)})

        # TASK-023: Generate DOCX
        step = {"key": "TASK-023", "title": "Generate DOCX reports", "status": "running"}
        pipeline_steps.append(step)
        _step_started(job_run, step["key"], step["title"], {"xlsx_total": len(xlsx_files)})

        docx_job = run_generate_docx_job(xlsx_files=xlsx_files, initiated_by=initiated_by)
        docx_result = docx_job.result_json or {}
        docx_files = docx_result.get("files", [])
        artifacts["docx_files"] = docx_files
        step["job_run_id"] = str(docx_job.id)
        step["summary"] = {
            "docx_total": docx_result.get("docx_total", 0),
            "docx_success": docx_result.get("docx_success", 0),
            "docx_failed": docx_result.get("docx_failed", 0),
        }
        step["status"] = docx_job.status

        if docx_result.get("docx_success", 0) == 0:
            reason = "DOCX generation produced no files"
            errors.append({"step": step["key"], "reason": reason, "job_run_id": str(docx_job.id)})
            _step_failed(job_run, step["key"], step["title"], reason, {"job_run_id": str(docx_job.id)})
            raise StopPipeline()

        _step_success(job_run, step["key"], step["title"], {"status": step["status"], **step["summary"]})

        # TASK-024: Convert DOCX to PDF
        step = {"key": "TASK-024", "title": "Convert DOCX to PDF", "status": "running"}
        pipeline_steps.append(step)
        _step_started(job_run, step["key"], step["title"], {"docx_total": len(docx_files)})

        pdf_result = run_convert_docx_to_pdf_step(docx_files=docx_files, job_run=job_run)
        pdf_files = pdf_result.get("pdf_files", [])
        artifacts["pdf_files"] = [item.get("path") for item in pdf_files]
        step["summary"] = {
            "pdf_total": pdf_result.get("pdf_total", 0),
            "pdf_success": pdf_result.get("pdf_success", 0),
            "pdf_failed": pdf_result.get("pdf_failed", 0),
        }

        if pdf_result.get("pdf_success", 0) == 0:
            step["status"] = "failed"
            reason = "PDF conversion produced no files"
            errors.append({"step": step["key"], "reason": reason})
            _step_failed(job_run, step["key"], step["title"], reason, step["summary"])
            raise StopPipeline()

        step["status"] = "partial" if pdf_result.get("pdf_failed", 0) > 0 else "success"
        _step_success(job_run, step["key"], step["title"], {"status": step["status"], **step["summary"]})

        # TASK-025: Send parent reports
        step = {"key": "TASK-025", "title": "Send parent reports", "status": "running"}
        pipeline_steps.append(step)
        contacts = _resolve_contacts()

        if not contacts:
            step["status"] = "failed"
            reason = "No contacts configured (PARENT_REPORTS_CONTACTS_JSON or PARENT_REPORTS_CONTACTS_CSV)"
            errors.append({"step": step["key"], "reason": reason})
            _step_failed(job_run, step["key"], step["title"], reason)
        else:
            _step_started(job_run, step["key"], step["title"], {"contacts_total": len(contacts)})
            parent_job = run_send_parent_reports_job(pdf_files=pdf_files, contacts=contacts, initiated_by=initiated_by)
            parent_result = parent_job.result_json or {}
            step["job_run_id"] = str(parent_job.id)
            step["status"] = parent_job.status
            step["summary"] = {
                "students_total": parent_result.get("students_total", 0),
                "sent_success": parent_result.get("sent_success", 0),
                "sent_failed": parent_result.get("sent_failed", 0),
                "skipped_no_contact": parent_result.get("skipped_no_contact", 0),
                "skipped_no_pdf": parent_result.get("skipped_no_pdf", 0),
            }
            if parent_job.status == JobRun.Status.FAILED:
                errors.append({"step": step["key"], "reason": "Parent reports sending failed", "job_run_id": str(parent_job.id)})
                _step_failed(job_run, step["key"], step["title"], "Parent reports sending failed", step["summary"])
            else:
                _step_success(job_run, step["key"], step["title"], {"status": step["status"], **step["summary"]})
    except StopPipeline:
        pass
    except Exception as exc:  # noqa: BLE001
        errors.append({"step": "orchestration", "reason": str(exc), "type": exc.__class__.__name__})
        log_step(
            job_run=job_run,
            level=JobLog.Level.ERROR,
            message="step_failed",
            context={"step": "orchestration", "title": "Full pipeline", "reason": str(exc)},
        )

    status_values = [step.get("status") for step in pipeline_steps]
    if any(value == JobRun.Status.FAILED or value == "failed" for value in status_values):
        final_status = JobRun.Status.FAILED
    elif any(value == JobRun.Status.PARTIAL or value == "partial" for value in status_values):
        final_status = JobRun.Status.PARTIAL
    elif status_values:
        final_status = JobRun.Status.SUCCESS
    else:
        final_status = JobRun.Status.FAILED

    summary = {
        "steps_total": len(pipeline_steps),
        "steps_success": sum(1 for value in status_values if value in {JobRun.Status.SUCCESS, "success"}),
        "steps_partial": sum(1 for value in status_values if value in {JobRun.Status.PARTIAL, "partial"}),
        "steps_failed": sum(1 for value in status_values if value in {JobRun.Status.FAILED, "failed"}),
    }

    job_run.status = final_status
    job_run.finished_at = timezone.now()
    job_run.result_json = {
        "pipeline_steps": pipeline_steps,
        "summary": summary,
        "artifacts": artifacts,
        "errors": errors,
    }
    job_run.save(update_fields=["status", "finished_at", "result_json"])

    return job_run