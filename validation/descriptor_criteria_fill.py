from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from django.db import close_old_connections
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from journal_links.models import ClassSheetLink
from validation.job_runner import fetch_workbook_for_link

JOB_TYPE = "descriptor_criteria_fill_check"


class DescriptorCriteriaFillReadError(ValueError):
    """Raised when a workbook cannot be read for descriptor/criteria checks."""


def _is_empty(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _normalize_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]*\|\s*", " | ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _classify_sheet_type(sheet_name: str) -> str:
    normalized_name = (sheet_name or "").strip().lower()
    if "тьютор" in normalized_name or "tutor" in normalized_name:
        return "tutor"
    if "служеб" in normalized_name or "service" in normalized_name:
        return "service"
    return "subject"


def _cell_value(ws, row_num: int, col_num: int) -> object:
    cell = ws._cells.get((row_num, col_num))
    return cell.value if cell is not None else None


def _iter_non_empty_cells(ws):
    for (row_num, col_num), cell in sorted(ws._cells.items()):
        if not _is_empty(cell.value):
            yield row_num, col_num, cell.value


def _get_real_data_bounds(ws) -> tuple[int, int]:
    max_row = 0
    max_col = 0
    for row_num, col_num, _value in _iter_non_empty_cells(ws):
        max_row = max(max_row, row_num)
        max_col = max(max_col, col_num)
    return max_row, max_col


def _find_anchor(ws, *tokens: str) -> tuple[int, int] | None:
    for row_num, col_num, value in _iter_non_empty_cells(ws):
        normalized = _normalize_text(value)
        if normalized and all(token in normalized for token in tokens):
            return row_num, col_num
    return None


def _cell_right_value(ws, anchor: tuple[int, int] | None) -> object:
    if anchor is None:
        return None
    row_num, col_num = anchor
    return _cell_value(ws, row_num, col_num + 1)


def _parse_module_number(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value

    text = str(value).strip()
    try:
        return int(float(text))
    except (TypeError, ValueError):
        match = re.search(r"\d+", text)
        return int(match.group(0)) if match else None


def _find_comment_col(ws, criteria_row: int, start_col: int, max_col: int) -> int | None:
    for col_num in range(start_col, max_col + 1):
        normalized = _normalize_text(_cell_value(ws, criteria_row, col_num))
        if "коммент" in normalized or "comment" in normalized:
            return col_num
    return None


def check_subject_sheet(ws, *, class_code: str, sheet_url: str) -> dict:
    max_row, max_col = _get_real_data_bounds(ws)
    class_anchor = _find_anchor(ws, "класс", "grade")
    teacher_anchor = _find_anchor(ws, "учитель", "teacher")
    module_anchor = _find_anchor(ws, "module")
    if module_anchor is None:
        module_anchor = _find_anchor(ws, "модуль")
    descriptor_anchor = _find_anchor(ws, "дескриптор", "descriptor")
    criteria_anchor = _find_anchor(ws, "критерии оценивания", "assessment criteria")

    teacher_name = str(_cell_right_value(ws, teacher_anchor) or "").strip()
    module_number = _parse_module_number(_cell_right_value(ws, module_anchor))
    descriptor_value = _cell_right_value(ws, descriptor_anchor)

    if descriptor_anchor is None:
        descriptor_status = "not_found"
    elif _is_empty(descriptor_value):
        descriptor_status = "missing"
    else:
        descriptor_status = "filled"

    criteria_total = 0
    criteria_filled = 0
    criteria_missing = 0
    criteria_status = "not_found"
    if criteria_anchor is not None:
        criteria_row, criteria_col = criteria_anchor
        comment_col = _find_comment_col(ws, criteria_row, criteria_col + 1, max_col)
        end_col = (comment_col - 1) if comment_col else max_col
        criteria_total = max(0, end_col - criteria_col)
        for col_num in range(criteria_col + 1, end_col + 1):
            value = _cell_value(ws, criteria_row, col_num)
            if _is_empty(value):
                criteria_missing += 1
            else:
                criteria_filled += 1
        criteria_status = "filled" if criteria_total > 0 and criteria_missing == 0 else "missing"

    overall_status = "ok"
    if descriptor_status != "filled" or criteria_status != "filled":
        overall_status = "problem"

    return {
        "class_code": class_code,
        "sheet_class_code": str(_cell_right_value(ws, class_anchor) or "").strip(),
        "subject_name": ws.title,
        "teacher_name": teacher_name,
        "module_number": module_number,
        "descriptor_status": descriptor_status,
        "criteria_status": criteria_status,
        "criteria_total": criteria_total,
        "criteria_filled": criteria_filled,
        "criteria_missing": criteria_missing,
        "overall_status": overall_status,
        "sheet_url": sheet_url,
        "sheet_name": ws.title,
    }


def check_workbook_descriptor_criteria(path: str, *, class_code: str, sheet_url: str) -> dict:
    wb = None
    try:
        wb = load_workbook(path, data_only=True)
    except (FileNotFoundError, InvalidFileException, BadZipFile, OSError) as exc:
        raise DescriptorCriteriaFillReadError(f"Cannot read workbook: {path}") from exc

    rows: list[dict] = []
    sheets_skipped = 0
    sheet_events: list[dict] = []
    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            sheet_type = _classify_sheet_type(sheet_name)
            sheet_events.append({"event": "sheet_detected", "sheet_name": sheet_name, "sheet_type": sheet_type})
            if sheet_type in {"tutor", "service"}:
                sheets_skipped += 1
                sheet_events.append({"event": "sheet_skipped", "sheet_name": sheet_name, "sheet_type": sheet_type})
                continue

            row = check_subject_sheet(ws, class_code=class_code, sheet_url=sheet_url)
            rows.append(row)
            sheet_events.append(
                {
                    "event": "sheet_checked",
                    "sheet_name": sheet_name,
                    "sheet_type": sheet_type,
                    "overall_status": row["overall_status"],
                }
            )

        return {
            "rows": rows,
            "summary": {
                "sheets_total": len(wb.sheetnames),
                "sheets_checked": len(rows),
                "sheets_skipped": sheets_skipped,
                "subjects_ok": sum(1 for row in rows if row["overall_status"] == "ok"),
                "subjects_with_problems": sum(1 for row in rows if row["overall_status"] != "ok"),
            },
            "sheet_events": sheet_events,
        }
    finally:
        if wb is not None:
            wb.close()


def _collect_links(*, class_code: str | None = None, all_active: bool = True) -> list[ClassSheetLink]:
    queryset = ClassSheetLink.objects.filter(is_active=True)
    if class_code:
        queryset = queryset.filter(class_code=class_code)
    elif not all_active:
        queryset = ClassSheetLink.objects.none()
    return list(queryset.order_by("class_code", "id"))


def enqueue_descriptor_criteria_fill_check_job(
    *,
    class_code: str | None = None,
    all_active: bool = True,
    initiated_by=None,
) -> JobRun:
    params = {"class_code": class_code, "all_active": all_active}
    job_run = JobRun.objects.create(
        job_type=JOB_TYPE,
        status=JobRun.Status.PENDING,
        started_at=timezone.now(),
        params_json=params,
        initiated_by=initiated_by,
    )
    log_step(
        job_run=job_run,
        level=JobLog.Level.INFO,
        message="Descriptor/criteria fill check queued",
        context=params,
    )
    thread = threading.Thread(
        target=_run_descriptor_criteria_fill_check_thread,
        args=(str(job_run.id), class_code, all_active),
        daemon=True,
    )
    thread.start()
    return job_run


def _run_descriptor_criteria_fill_check_thread(job_run_id: str, class_code: str | None, all_active: bool) -> None:
    close_old_connections()
    try:
        job_run = JobRun.objects.get(id=job_run_id)
        run_descriptor_criteria_fill_check_job(class_code=class_code, all_active=all_active, job_run=job_run)
    except Exception as exc:  # noqa: BLE001
        try:
            job_run = JobRun.objects.get(id=job_run_id)
            job_run.status = JobRun.Status.FAILED
            job_run.finished_at = timezone.now()
            job_run.result_json = {"summary": {}, "rows": [], "tables": [], "error": str(exc)}
            job_run.save(update_fields=["status", "finished_at", "result_json"])
            log_step(
                job_run=job_run,
                level=JobLog.Level.ERROR,
                message="Descriptor/criteria fill check background worker failed",
                context={"reason": str(exc)},
            )
        except Exception:
            pass
    finally:
        close_old_connections()


def run_descriptor_criteria_fill_check_job(
    *,
    class_code: str | None = None,
    all_active: bool = True,
    initiated_by=None,
    job_run: JobRun | None = None,
) -> JobRun:
    links = _collect_links(class_code=class_code, all_active=all_active)
    params = {"class_code": class_code, "all_active": all_active}
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
    log_step(
        job_run=job_run,
        level=JobLog.Level.INFO,
        message="Descriptor/criteria fill check started",
        context={"links_count": len(links), **params},
    )

    rows: list[dict] = []
    tables: list[dict] = []
    tables_success = 0
    tables_failed = 0
    sheets_total = 0
    sheets_checked = 0
    sheets_skipped = 0
    classes_checked: set[str] = set()

    try:
        for link in links:
            classes_checked.add(link.class_code)
            temp_file: Path | None = None
            log_step(
                job_run=job_run,
                level=JobLog.Level.INFO,
                message="Class check started",
                context={"link_id": link.id, "class_code": link.class_code},
            )
            try:
                temp_file = fetch_workbook_for_link(link)
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.INFO,
                    message="Workbook downloaded",
                    context={"link_id": link.id, "class_code": link.class_code},
                )

                workbook_result = check_workbook_descriptor_criteria(
                    str(temp_file),
                    class_code=link.class_code,
                    sheet_url=link.google_sheet_url,
                )
                table_rows = workbook_result["rows"]
                table_summary = workbook_result["summary"]
                rows.extend(table_rows)
                tables_success += 1
                sheets_total += int(table_summary["sheets_total"])
                sheets_checked += int(table_summary["sheets_checked"])
                sheets_skipped += int(table_summary["sheets_skipped"])

                for event in workbook_result["sheet_events"]:
                    if event["event"] == "sheet_skipped":
                        log_step(
                            job_run=job_run,
                            level=JobLog.Level.INFO,
                            message="Sheet skipped",
                            context={
                                "link_id": link.id,
                                "class_code": link.class_code,
                                "sheet_name": event["sheet_name"],
                                "sheet_type": event["sheet_type"],
                            },
                        )
                    elif event["event"] == "sheet_checked":
                        log_step(
                            job_run=job_run,
                            level=JobLog.Level.INFO,
                            message="Sheet checked",
                            context={
                                "link_id": link.id,
                                "class_code": link.class_code,
                                "sheet_name": event["sheet_name"],
                                "overall_status": event["overall_status"],
                            },
                        )

                problems_count = sum(1 for row in table_rows if row["overall_status"] != "ok")
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.INFO,
                    message="Problems found",
                    context={"link_id": link.id, "class_code": link.class_code, "problems_count": problems_count},
                )
                tables.append(
                    {
                        "link_id": link.id,
                        "class_code": link.class_code,
                        "status": "success",
                        "summary": table_summary,
                    }
                )
            except Exception as exc:
                tables_failed += 1
                tables.append(
                    {
                        "link_id": link.id,
                        "class_code": link.class_code,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.ERROR,
                    message="Class check failed",
                    context={"link_id": link.id, "class_code": link.class_code, "reason": str(exc)},
                )
            finally:
                if temp_file and temp_file.exists():
                    try:
                        temp_file.unlink(missing_ok=True)
                    except PermissionError as exc:
                        log_step(
                            job_run=job_run,
                            level=JobLog.Level.WARNING,
                            message="Could not remove temporary workbook file",
                            context={"path": str(temp_file), "reason": str(exc)},
                        )

        summary = {
            "classes_checked": len(classes_checked),
            "subjects_checked": len(rows),
            "fully_filled": sum(1 for row in rows if row["overall_status"] == "ok"),
            "with_problems": sum(1 for row in rows if row["overall_status"] != "ok"),
            "tables_total": len(links),
            "tables_success": tables_success,
            "tables_failed": tables_failed,
            "sheets_total": sheets_total,
            "sheets_checked": sheets_checked,
            "sheets_skipped": sheets_skipped,
        }
        if not links or tables_success == 0:
            final_status = JobRun.Status.FAILED
        elif tables_failed > 0:
            final_status = JobRun.Status.PARTIAL
        else:
            final_status = JobRun.Status.SUCCESS

        job_run.result_json = {"summary": summary, "rows": rows, "tables": tables}
        job_run.status = final_status
        job_run.finished_at = timezone.now()
        job_run.save(update_fields=["result_json", "status", "finished_at"])
        log_step(
            job_run=job_run,
            level=JobLog.Level.INFO,
            message="Descriptor/criteria fill check finished",
            context={"status": final_status, "summary": summary},
        )
    except Exception as exc:
        job_run.status = JobRun.Status.FAILED
        job_run.finished_at = timezone.now()
        job_run.result_json = {"summary": {}, "rows": rows, "tables": tables, "error": str(exc)}
        job_run.save(update_fields=["status", "finished_at", "result_json"])
        log_step(
            job_run=job_run,
            level=JobLog.Level.ERROR,
            message="Descriptor/criteria fill check failed",
            context={"reason": str(exc)},
        )

    return job_run
