from __future__ import annotations

import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from django.db import close_old_connections
from django.utils import timezone

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from journal_links.models import ClassSheetLink
from pipeline.legacy_docx import LegacyDocxGenerator
from pipeline.services_upload import extract_drive_folder_id, upload_docx_files_to_drive_folder
from validation.job_runner import fetch_workbook_for_link

JOB_TYPE = "prepare_student_review_reports"


def _is_primary_class(class_code: str) -> bool:
    match = re.match(r"\s*(\d+)", str(class_code or ""))
    return bool(match and int(match.group(1)) in {0, 1, 2, 3})


def _safe_docx_name(class_code: str, name: str) -> str:
    stem = Path(name).stem.strip() or "student"
    raw = f"{class_code} {stem}.docx"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", raw).strip()


def _docx_entries(paths: list[str], *, class_code: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for raw_path in paths:
        path = Path(raw_path)
        target = path.with_name(_safe_docx_name(class_code, path.name))
        if target != path:
            path.replace(target)
        entries.append(
            {
                "path": str(target),
                "name": target.name,
                "class_code": class_code,
                "student_name": target.stem.removeprefix(f"{class_code} ").strip(),
            }
        )
    return entries


def _params(
    *,
    link: ClassSheetLink,
    drive_folder_url: str,
    drive_folder_id: str,
    module_number: int,
    module_dates: str,
) -> dict[str, Any]:
    return {
        "class_code": link.class_code,
        "class_sheet_link_id": link.id,
        "drive_folder_url": drive_folder_url,
        "drive_folder_id": drive_folder_id,
        "module_number": module_number,
        "module_dates": module_dates,
        "output_format": "docx",
        "trigger": "manual",
    }


def enqueue_prepare_student_review_reports_job(
    *,
    class_sheet_link_id: int,
    drive_folder_url: str,
    module_number: int,
    module_dates: str,
    initiated_by=None,
) -> JobRun:
    link = ClassSheetLink.objects.get(id=class_sheet_link_id, is_active=True)
    drive_folder_id = extract_drive_folder_id(drive_folder_url)
    params = _params(
        link=link,
        drive_folder_url=drive_folder_url,
        drive_folder_id=drive_folder_id,
        module_number=module_number,
        module_dates=module_dates,
    )
    job_run = JobRun.objects.create(
        job_type=JOB_TYPE,
        status=JobRun.Status.PENDING,
        started_at=timezone.now(),
        params_json=params,
        initiated_by=initiated_by,
    )
    log_step(job_run=job_run, level=JobLog.Level.INFO, message="Student review DOCX reports queued", context=params)
    thread = threading.Thread(
        target=_run_prepare_student_review_reports_thread,
        args=(str(job_run.id),),
        daemon=True,
    )
    thread.start()
    return job_run


def _run_prepare_student_review_reports_thread(job_run_id: str) -> None:
    close_old_connections()
    try:
        job_run = JobRun.objects.get(id=job_run_id)
        params = job_run.params_json or {}
        run_prepare_student_review_reports_job(
            class_sheet_link_id=int(params["class_sheet_link_id"]),
            drive_folder_url=str(params["drive_folder_url"]),
            module_number=int(params["module_number"]),
            module_dates=str(params.get("module_dates") or ""),
            initiated_by=job_run.initiated_by,
            job_run=job_run,
        )
    except Exception as exc:  # noqa: BLE001
        try:
            job_run = JobRun.objects.get(id=job_run_id)
            job_run.status = JobRun.Status.FAILED
            job_run.finished_at = timezone.now()
            job_run.result_json = {"error": str(exc), "summary": {}}
            job_run.save(update_fields=["status", "finished_at", "result_json"])
            log_step(job_run=job_run, level=JobLog.Level.ERROR, message="Student review DOCX reports failed", context={"error": str(exc)})
        except Exception:
            pass
    finally:
        close_old_connections()


def run_prepare_student_review_reports_job(
    *,
    class_sheet_link_id: int,
    drive_folder_url: str,
    module_number: int,
    module_dates: str,
    initiated_by=None,
    job_run: JobRun | None = None,
    generator: LegacyDocxGenerator | None = None,
) -> JobRun:
    link = ClassSheetLink.objects.get(id=class_sheet_link_id, is_active=True)
    drive_folder_id = extract_drive_folder_id(drive_folder_url)
    params = _params(
        link=link,
        drive_folder_url=drive_folder_url,
        drive_folder_id=drive_folder_id,
        module_number=module_number,
        module_dates=module_dates,
    )

    if job_run is None:
        job_run = JobRun.objects.create(
            job_type=JOB_TYPE,
            status=JobRun.Status.RUNNING,
            started_at=timezone.now(),
            params_json=params,
            initiated_by=initiated_by,
        )
    else:
        job_run.status = JobRun.Status.RUNNING
        job_run.started_at = job_run.started_at or timezone.now()
        job_run.finished_at = None
        job_run.params_json = params
        job_run.result_json = {}
        job_run.save(update_fields=["status", "started_at", "finished_at", "params_json", "result_json"])

    log_step(job_run=job_run, level=JobLog.Level.INFO, message="Student review DOCX reports started", context=params)

    temp_root = Path(tempfile.mkdtemp(prefix=f"student_review_{link.class_code}_"))
    workbook_path: Path | None = None
    errors: list[dict[str, Any]] = []
    docx_entries: list[dict[str, str]] = []
    upload_result = {
        "uploaded_total": 0,
        "uploaded_success": 0,
        "uploaded_failed": 0,
        "uploaded_created": 0,
        "uploaded_updated": 0,
        "uploaded_files": [],
        "errors": [],
    }
    local_temp_removed = False

    try:
        workbook_path = fetch_workbook_for_link(link)
        log_step(
            job_run=job_run,
            level=JobLog.Level.INFO,
            message="Class workbook downloaded",
            context={"class_code": link.class_code, "path": str(workbook_path)},
        )

        primary_school = _is_primary_class(link.class_code)
        school_level = "primary" if primary_school else "secondary"
        include_tutor = not primary_school
        generator = generator or LegacyDocxGenerator()
        output_dir = temp_root / "docx"
        generation_temp_dir = temp_root / "generation_temp"

        created_paths = generator.generate_for_workbook(
            workbook_path=workbook_path,
            output_dir=output_dir,
            temp_dir=generation_temp_dir,
            module_number=module_number,
            module_dates=module_dates,
            school_level=school_level,
            include_tutor=include_tutor,
        )
        docx_entries = _docx_entries(created_paths, class_code=link.class_code)
        log_step(
            job_run=job_run,
            level=JobLog.Level.INFO,
            message="Students found for DOCX reports",
            context={"class_code": link.class_code, "students_found": len(docx_entries)},
        )
        for entry in docx_entries:
            log_step(
                job_run=job_run,
                level=JobLog.Level.INFO,
                message="DOCX created for student",
                context={"student_name": entry["student_name"], "path": entry["path"], "class_code": link.class_code},
            )

        upload_result = upload_docx_files_to_drive_folder(
            docx_files=docx_entries,
            folder_id=drive_folder_id,
            job_run=job_run,
            duplicate_strategy="update",
        )
        errors.extend(upload_result.get("errors", []))

        if not docx_entries:
            final_status = JobRun.Status.FAILED
        elif upload_result.get("uploaded_failed", 0):
            final_status = JobRun.Status.PARTIAL
        else:
            final_status = JobRun.Status.SUCCESS

        result_json = {
            "summary": {
                "students_found": len(docx_entries),
                "docx_created": len(docx_entries),
                "uploaded_success": upload_result.get("uploaded_success", 0),
                "uploaded_created": upload_result.get("uploaded_created", 0),
                "uploaded_updated": upload_result.get("uploaded_updated", 0),
                "uploaded_failed": upload_result.get("uploaded_failed", 0),
                "errors": len(errors),
            },
            "class_code": link.class_code,
            "drive_folder_url": drive_folder_url,
            "drive_folder_id": drive_folder_id,
            "module_number": module_number,
            "module_dates": module_dates,
            "school_level": school_level,
            "include_tutor": include_tutor,
            "files": docx_entries,
            "uploaded_files": upload_result.get("uploaded_files", []),
            "errors": errors,
        }
        job_run.result_json = result_json
        job_run.status = final_status
        job_run.finished_at = timezone.now()
        job_run.save(update_fields=["result_json", "status", "finished_at"])
        log_step(job_run=job_run, level=JobLog.Level.INFO, message="Student review DOCX reports finished", context={"status": final_status, **result_json["summary"]})
    except Exception as exc:  # noqa: BLE001
        errors.append({"error": str(exc), "type": exc.__class__.__name__})
        job_run.result_json = {
            "summary": {
                "students_found": len(docx_entries),
                "docx_created": len(docx_entries),
                "uploaded_success": upload_result.get("uploaded_success", 0),
                "uploaded_created": upload_result.get("uploaded_created", 0),
                "uploaded_updated": upload_result.get("uploaded_updated", 0),
                "uploaded_failed": upload_result.get("uploaded_failed", 0),
                "errors": len(errors),
            },
            "class_code": link.class_code,
            "drive_folder_url": drive_folder_url,
            "drive_folder_id": drive_folder_id,
            "module_number": module_number,
            "module_dates": module_dates,
            "files": docx_entries,
            "uploaded_files": upload_result.get("uploaded_files", []),
            "errors": errors,
        }
        job_run.status = JobRun.Status.FAILED
        job_run.finished_at = timezone.now()
        job_run.save(update_fields=["result_json", "status", "finished_at"])
        log_step(job_run=job_run, level=JobLog.Level.ERROR, message="Student review DOCX reports failed", context={"error": str(exc), "type": exc.__class__.__name__})
    finally:
        if workbook_path and workbook_path.exists():
            try:
                workbook_path.unlink(missing_ok=True)
            except PermissionError:
                pass
        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        local_temp_removed = not temp_root.exists()
        result_json = job_run.result_json if isinstance(job_run.result_json, dict) else {}
        result_json["local_temp_removed"] = local_temp_removed
        job_run.result_json = result_json
        job_run.save(update_fields=["result_json"])
        log_step(
            job_run=job_run,
            level=JobLog.Level.INFO,
            message="Local temporary DOCX files removed",
            context={"temp_root": str(temp_root), "removed": local_temp_removed},
        )

    return job_run
