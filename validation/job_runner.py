from __future__ import annotations

import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from django.utils import timezone

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from journal_links.models import ClassSheetLink
from validation.services import validate_workbook

_GOOGLE_SHEET_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def _extract_google_sheet_file_id(url: str) -> str | None:
    match = _GOOGLE_SHEET_RE.search(url or "")
    if not match:
        return None
    return match.group(1)


def _extract_gid(url: str) -> str | None:
    parsed = urlparse(url)
    query_gid = parse_qs(parsed.query).get("gid", [None])[0]
    if query_gid:
        return query_gid

    if parsed.fragment:
        for part in parsed.fragment.split("&"):
            if part.startswith("gid="):
                return part.replace("gid=", "", 1)

    return None


def _build_export_url(url: str) -> str:
    file_id = _extract_google_sheet_file_id(url)
    if not file_id:
        return url

    export_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
    gid = _extract_gid(url)
    if gid:
        export_url = f"{export_url}&gid={gid}"
    return export_url


def fetch_workbook_for_link(link: ClassSheetLink) -> Path:
    export_url = _build_export_url(link.google_sheet_url)

    with urlopen(export_url, timeout=30) as response:
        data = response.read()

    with tempfile.NamedTemporaryFile(prefix="validation_", suffix=".xlsx", delete=False) as tmp_file:
        tmp_file.write(data)
        return Path(tmp_file.name)


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


def run_validation_job(
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
        job_type="validation",
        status=JobRun.Status.RUNNING,
        started_at=timezone.now(),
        params_json=params,
        initiated_by=initiated_by,
    )

    log_step(
        job_run=job_run,
        level=JobLog.Level.INFO,
        message="Validation run started",
        context={"links_count": len(links), **params},
    )

    aggregated_issues: list[dict] = []
    tables: list[dict] = []
    tables_success = 0
    tables_failed = 0

    try:
        for link in links:
            log_step(
                job_run=job_run,
                level=JobLog.Level.INFO,
                message="Start validating table",
                context={"link_id": link.id, "class_code": link.class_code, "subject": link.subject_name},
            )

            temp_file: Path | None = None
            try:
                temp_file = fetch_workbook_for_link(link)
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.DEBUG,
                    message="Workbook downloaded",
                    context={"link_id": link.id, "path": str(temp_file)},
                )

                result = validate_workbook(str(temp_file))
                issues = result.get("issues", [])
                summary = result.get("summary", {})
                aggregated_issues.extend(issues)

                tables.append(
                    {
                        "link_id": link.id,
                        "class_code": link.class_code,
                        "subject_name": link.subject_name,
                        "teacher_name": link.teacher_name,
                        "status": "success",
                        "summary": summary,
                        "issues_count": len(issues),
                    }
                )
                tables_success += 1

                log_step(
                    job_run=job_run,
                    level=JobLog.Level.INFO,
                    message="Table validation completed",
                    context={
                        "link_id": link.id,
                        "class_code": link.class_code,
                        "issues_count": len(issues),
                        "summary": summary,
                    },
                )
            except Exception as exc:
                tables_failed += 1
                tables.append(
                    {
                        "link_id": link.id,
                        "class_code": link.class_code,
                        "subject_name": link.subject_name,
                        "teacher_name": link.teacher_name,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.ERROR,
                    message=f"Table validation failed: {exc}",
                    context={"link_id": link.id, "class_code": link.class_code},
                )
            finally:
                if temp_file and temp_file.exists():
                    temp_file.unlink(missing_ok=True)

        summary = {
            "total": len(aggregated_issues),
            "critical": sum(1 for issue in aggregated_issues if issue.get("severity") == "critical"),
            "warning": sum(1 for issue in aggregated_issues if issue.get("severity") == "warning"),
            "info": sum(1 for issue in aggregated_issues if issue.get("severity") == "info"),
            "tables_total": len(links),
            "tables_success": tables_success,
            "tables_failed": tables_failed,
        }

        if not links or tables_success == 0:
            final_status = JobRun.Status.FAILED
        elif tables_failed > 0:
            final_status = JobRun.Status.PARTIAL
        else:
            final_status = JobRun.Status.SUCCESS

        result_json = {
            "summary": summary,
            "issues": aggregated_issues,
            "tables": tables,
        }

        job_run.result_json = result_json
        job_run.status = final_status
        job_run.finished_at = timezone.now()
        job_run.save(update_fields=["result_json", "status", "finished_at"])

        log_step(
            job_run=job_run,
            level=JobLog.Level.INFO,
            message="Validation run finished",
            context={"status": final_status, "summary": summary},
        )
    except Exception as exc:
        job_run.status = JobRun.Status.FAILED
        job_run.finished_at = timezone.now()
        job_run.save(update_fields=["status", "finished_at"])
        log_step(job_run=job_run, level=JobLog.Level.ERROR, message=f"Validation run failed: {exc}")

    return job_run