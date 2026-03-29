from __future__ import annotations

import tempfile
from pathlib import Path

from django.utils import timezone

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from pipeline.legacy_docx import LegacyDocxGenerationError, LegacyDocxGenerator


def _class_code_from_xlsx_path(file_path: Path) -> str:
    name = file_path.stem
    if name.startswith("journal_"):
        return name.replace("journal_", "", 1)
    return name


def run_generate_docx_job(
    *,
    xlsx_files: list[str],
    output_root: str = "output",
    initiated_by=None,
) -> JobRun:
    params = {
        "xlsx_files": xlsx_files,
        "output_root": output_root,
    }

    job_run = JobRun.objects.create(
        job_type="generate_docx_reports",
        status=JobRun.Status.RUNNING,
        started_at=timezone.now(),
        params_json=params,
        initiated_by=initiated_by,
    )

    log_step(
        job_run=job_run,
        level=JobLog.Level.INFO,
        message="DOCX generation started",
        context={"xlsx_count": len(xlsx_files), "output_root": output_root},
    )

    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)

    docx_total = 0
    docx_success = 0
    docx_failed = 0
    all_files: list[str] = []
    output_dirs: list[str] = []
    errors: list[dict] = []
    classes: list[dict] = []

    generator = LegacyDocxGenerator()

    try:
        for file_raw in xlsx_files:
            workbook_path = Path(file_raw)
            class_code = _class_code_from_xlsx_path(workbook_path)
            class_output_dir = output_root_path / class_code
            output_dirs.append(str(class_output_dir))

            class_summary = {
                "class_code": class_code,
                "source_xlsx": str(workbook_path),
                "output_dir": str(class_output_dir),
                "docx_created": 0,
                "status": "failed",
                "errors": [],
            }

            log_step(
                job_run=job_run,
                level=JobLog.Level.INFO,
                message="Class DOCX generation start",
                context={
                    "class_code": class_code,
                    "source_xlsx": str(workbook_path),
                    "output_dir": str(class_output_dir),
                },
            )

            try:
                if not workbook_path.exists():
                    raise FileNotFoundError(f"Workbook not found: {workbook_path}")

                with tempfile.TemporaryDirectory(prefix=f"docx_tmp_{class_code}_") as temp_dir:
                    created = generator.generate_for_workbook(
                        workbook_path=workbook_path,
                        output_dir=class_output_dir,
                        temp_dir=Path(temp_dir),
                    )

                created_count = len(created)
                docx_total += created_count
                docx_success += created_count
                all_files.extend(created)

                class_summary["docx_created"] = created_count
                class_summary["status"] = "success"

                log_step(
                    job_run=job_run,
                    level=JobLog.Level.INFO,
                    message="Class DOCX generation summary",
                    context={
                        "class_code": class_code,
                        "docx_created": created_count,
                        "output_dir": str(class_output_dir),
                        "status": "success",
                    },
                )
            except Exception as exc:  # noqa: BLE001
                error_payload = {
                    "class_code": class_code,
                    "source_xlsx": str(workbook_path),
                    "error": str(exc),
                    "type": exc.__class__.__name__,
                }
                errors.append(error_payload)
                class_summary["errors"].append(error_payload)

                log_step(
                    job_run=job_run,
                    level=JobLog.Level.ERROR,
                    message=f"Class DOCX generation failed: {exc}",
                    context=error_payload,
                )
            finally:
                classes.append(class_summary)

        docx_failed = sum(1 for item in errors)

        if not xlsx_files or docx_success == 0:
            final_status = JobRun.Status.FAILED
        elif docx_failed > 0:
            final_status = JobRun.Status.PARTIAL
        else:
            final_status = JobRun.Status.SUCCESS

        result_json = {
            "docx_total": docx_total,
            "docx_success": docx_success,
            "docx_failed": docx_failed,
            "output_dirs": output_dirs,
            "files": all_files,
            "errors": errors,
            "classes": classes,
        }

        job_run.result_json = result_json
        job_run.status = final_status
        job_run.finished_at = timezone.now()
        job_run.save(update_fields=["result_json", "status", "finished_at"])

        log_step(
            job_run=job_run,
            level=JobLog.Level.INFO,
            message="DOCX generation finished",
            context={
                "status": final_status,
                "docx_total": docx_total,
                "docx_success": docx_success,
                "docx_failed": docx_failed,
            },
        )
    except LegacyDocxGenerationError as exc:
        job_run.status = JobRun.Status.FAILED
        job_run.finished_at = timezone.now()
        job_run.save(update_fields=["status", "finished_at"])
        log_step(job_run=job_run, level=JobLog.Level.ERROR, message=f"DOCX generation failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        job_run.status = JobRun.Status.FAILED
        job_run.finished_at = timezone.now()
        job_run.save(update_fields=["status", "finished_at"])
        log_step(job_run=job_run, level=JobLog.Level.ERROR, message=f"DOCX generation failed: {exc}")

    return job_run