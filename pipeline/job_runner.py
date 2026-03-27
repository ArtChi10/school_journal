from __future__ import annotations

from pathlib import Path

from django.db import transaction
from django.utils import timezone

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from journal_links.models import ClassSheetLink
from pipeline.models import CriterionEntry
from pipeline.services import (
    CriterionNormalizationError,
    WorkbookReadError,
    normalize_criterion_text_with_ai,
    extract_raw_criteria_from_workbook,
)
from validation.job_runner import fetch_workbook_for_link


def _collect_links(link_id: int | None, class_code: str | None, all_active: bool) -> list[ClassSheetLink]:
    queryset = ClassSheetLink.objects.filter(is_active=True)

    if link_id is not None:
        queryset = queryset.filter(id=link_id)
    elif class_code:
        queryset = queryset.filter(class_code=class_code)
    elif all_active:
        queryset = queryset
    else:
        queryset = ClassSheetLink.objects.none()

    return list(queryset.order_by("id"))


def run_build_criteria_job(
    *,
    link_id: int | None = None,
    class_code: str | None = None,
    all_active: bool = False,
    initiated_by=None,
) -> JobRun:
    links = _collect_links(link_id=link_id, class_code=class_code, all_active=all_active)
    params = {
        "link_id": link_id,
        "class_code": class_code,
        "all_active": all_active,
    }

    job_run = JobRun.objects.create(
        job_type="build_criteria_table",
        status=JobRun.Status.RUNNING,
        started_at=timezone.now(),
        params_json=params,
        initiated_by=initiated_by,
    )

    log_step(
        job_run=job_run,
        level=JobLog.Level.INFO,
        message="Criteria table build started",
        context={"links_count": len(links), **params},
    )

    total_criteria = 0
    ai_ok = 0
    ai_failed = 0
    updated_rows = 0
    total_sheets_keys: set[tuple[str, str]] = set()
    tables_failed = 0

    try:
        for link in links:
            temp_file: Path | None = None
            try:
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.INFO,
                    message="Start processing table",
                    context={"link_id": link.id, "class_code": link.class_code, "subject": link.subject_name},
                )
                temp_file = fetch_workbook_for_link(link)
                rows = extract_raw_criteria_from_workbook(str(temp_file), class_code=link.class_code)
                total_criteria += len(rows)

                with transaction.atomic():
                    for row in rows:
                        total_sheets_keys.add((row["source_workbook"], row["source_sheet_name"]))

                        criterion_text_ai = ""
                        try:
                            criterion_text_ai = normalize_criterion_text_with_ai(row["criterion_text"])
                            if criterion_text_ai:
                                ai_ok += 1
                        except CriterionNormalizationError:
                            ai_failed += 1

                        _, _created = CriterionEntry.objects.update_or_create(
                            class_code=row["class_code"],
                            subject_name=row["subject_name"],
                            module_number=row["module_number"],
                            criterion_text=row["criterion_text"],
                            defaults={
                                "teacher_name": row["teacher_name"],
                                "criterion_text_ai": criterion_text_ai,
                                "source_sheet_name": row["source_sheet_name"],
                                "source_workbook": row["source_workbook"],
                            },
                        )
                        updated_rows += 1

                log_step(
                    job_run=job_run,
                    level=JobLog.Level.INFO,
                    message="Table processed",
                    context={
                        "link_id": link.id,
                        "class_code": link.class_code,
                        "criteria_count": len(rows),
                    },
                )
            except WorkbookReadError as exc:
                tables_failed += 1
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.ERROR,
                    message=f"Workbook read failed: {exc}",
                    context={"link_id": link.id, "class_code": link.class_code},
                )
            except Exception as exc:
                tables_failed += 1
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.ERROR,
                    message=f"Table processing failed: {exc}",
                    context={"link_id": link.id, "class_code": link.class_code},
                )
            finally:
                if temp_file and temp_file.exists():
                    temp_file.unlink(missing_ok=True)

        summary = {
            "total_sheets": len(total_sheets_keys),
            "total_criteria": total_criteria,
            "ai_ok": ai_ok,
            "ai_failed": ai_failed,
        }

        if not links or (total_criteria == 0 and tables_failed > 0):
            final_status = JobRun.Status.FAILED
        elif tables_failed > 0 or ai_failed > 0:
            final_status = JobRun.Status.PARTIAL
        else:
            final_status = JobRun.Status.SUCCESS

        job_run.result_json = {
            "summary": summary,
            "links_total": len(links),
            "links_failed": tables_failed,
            "rows_upserted": updated_rows,
        }
        job_run.status = final_status
        job_run.finished_at = timezone.now()
        job_run.save(update_fields=["result_json", "status", "finished_at"])

        log_step(
            job_run=job_run,
            level=JobLog.Level.INFO,
            message="Criteria table build finished",
            context={"status": final_status, "summary": summary},
        )
    except Exception as exc:
        job_run.status = JobRun.Status.FAILED
        job_run.finished_at = timezone.now()
        job_run.save(update_fields=["status", "finished_at"])
        log_step(job_run=job_run, level=JobLog.Level.ERROR, message=f"Build failed: {exc}")

    return job_run