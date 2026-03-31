from __future__ import annotations
import os
import re
import tempfile
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from django.utils import timezone

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from journal_links.models import ClassSheetLink
from notifications.models import NotificationEvent
from notifications.services import TelegramSendError, send_telegram
from validation.admin_summary import build_missing_data_summary, split_summary_for_telegram
from validation.services import validate_workbook
from django.conf import settings
import hashlib
import json

_GOOGLE_SHEET_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
GOOGLE_ACCESS_MODE_PUBLIC = "public_link"
GOOGLE_ACCESS_MODE_OAUTH_OWNER = "oauth_owner"
GOOGLE_ACCESS_MODE_DEFAULT = GOOGLE_ACCESS_MODE_PUBLIC
GOOGLE_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


class GoogleWorkbookAccessError(RuntimeError):
    """Raised when workbook download from Google Drive/Sheets fails."""


def get_google_access_mode() -> str:
    mode = os.getenv("GOOGLE_ACCESS_MODE", GOOGLE_ACCESS_MODE_DEFAULT).strip().lower()
    if mode not in {GOOGLE_ACCESS_MODE_PUBLIC, GOOGLE_ACCESS_MODE_OAUTH_OWNER}:
        raise GoogleWorkbookAccessError(
            "Invalid GOOGLE_ACCESS_MODE value "
            f"'{mode}'. Allowed: {GOOGLE_ACCESS_MODE_PUBLIC}|{GOOGLE_ACCESS_MODE_OAUTH_OWNER}."
        )
    return mode

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


def _require_env_path(var_name: str) -> Path:
    raw = (os.getenv(var_name) or "").strip()
    if not raw:
        raise GoogleWorkbookAccessError(f"{var_name} is required when GOOGLE_ACCESS_MODE=oauth_owner")

    path = Path(raw)
    if not path.exists():
        raise GoogleWorkbookAccessError(f"{var_name} file does not exist: {path}")

    return path

def _download_workbook_public_link(link: ClassSheetLink) -> Path:
    export_url = _build_export_url(link.google_sheet_url)
    with urlopen(export_url, timeout=30) as response:
        data = response.read()

    with tempfile.NamedTemporaryFile(prefix="validation_", suffix=".xlsx", delete=False) as tmp_file:
        tmp_file.write(data)
        return Path(tmp_file.name)

def _download_workbook_oauth_owner(link: ClassSheetLink) -> Path:
    _ = _require_env_path("GOOGLE_OAUTH_CLIENT_SECRET_PATH")
    token_path = _require_env_path("GOOGLE_OAUTH_TOKEN_PATH")
    file_id = _extract_google_sheet_file_id(link.google_sheet_url)
    if not file_id:
        raise GoogleWorkbookAccessError(f"Could not extract Google Sheet file id from URL: {link.google_sheet_url}")

    # Imports are local to avoid hard dependency during startup in environments
    # where Google packages may be absent until this mode is used.
    from google.auth.transport.requests import Request
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(token_path), GOOGLE_OAUTH_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise GoogleWorkbookAccessError(
                "OAuth token is invalid and cannot be refreshed. Re-authorize and recreate GOOGLE_OAUTH_TOKEN_PATH."
            )

    export_url = _build_export_url(link.google_sheet_url)
    session = AuthorizedSession(creds)
    response = session.get(export_url, timeout=30)
    if response.status_code >= 400:
        body_preview = (response.text or "").strip().replace("\n", " ")[:240]
        raise GoogleWorkbookAccessError(
            f"OAuth download failed: HTTP {response.status_code}. "
            f"URL={export_url}. Response={body_preview}"
        )

    with tempfile.NamedTemporaryFile(prefix="validation_", suffix=".xlsx", delete=False) as tmp_file:
        tmp_file.write(response.content)
        return Path(tmp_file.name)


def fetch_workbook_for_link(link: ClassSheetLink) -> Path:
    mode = get_google_access_mode()
    if mode == GOOGLE_ACCESS_MODE_OAUTH_OWNER:
        return _download_workbook_oauth_owner(link)
    return _download_workbook_public_link(link)




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

def fetch_workbook_for_link(link: ClassSheetLink) -> Path:
    mode = get_google_access_mode()
    if mode == GOOGLE_ACCESS_MODE_OAUTH_OWNER:
        return _download_workbook_oauth_owner(link)
    return _download_workbook_public_link(link)

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
    sheets_total = 0
    sheets_validated = 0
    sheets_skipped = 0
    students_total = 0
    issues_by_code: dict[str, int] = {}

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
                sheet_events = result.get("sheet_events", [])
                aggregated_issues.extend(issues)
                sheets_total += int(summary.get("sheets_total", 0))
                sheets_validated += int(summary.get("sheets_validated", 0))
                sheets_skipped += int(summary.get("sheets_skipped", 0))
                students_total += int(summary.get("students_total", 0))
                for code, count in (summary.get("issues_by_code", {}) or {}).items():
                    issues_by_code[code] = issues_by_code.get(code, 0) + int(count)

                for event in sheet_events:
                    event_type = event.get("event")
                    if event_type not in {"sheet_detected", "sheet_skipped", "sheet_validated"}:
                        continue
                    log_step(
                        job_run=job_run,
                        level=JobLog.Level.INFO,
                        message=event_type,
                        context={
                            "link_id": link.id,
                            "class_code": link.class_code,
                            "sheet_name": event.get("sheet_name"),
                            "sheet_type": event.get("sheet_type"),
                        },
                    )

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
            "sheets_total": sheets_total,
            "sheets_validated": sheets_validated,
            "sheets_skipped": sheets_skipped,
            "students_total": students_total,
            "issues_by_code": issues_by_code,
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

def _normalize_issue_context(issue: dict, link: ClassSheetLink) -> dict:
    issue = dict(issue)
    issue["teacher_name"] = (issue.get("teacher_name") or "").strip() or link.teacher_name
    issue["class_code"] = (issue.get("class_code") or "").strip() or link.class_code
    issue["subject_name"] = (issue.get("subject_name") or "").strip() or link.subject_name
    if not issue.get("issue_group"):
        code = issue.get("code")
        if code == "DESCRIPTOR_EMPTY":
            issue["issue_group"] = "descriptor"
        elif code == "CRITERIA_HEADERS_EMPTY":
            issue["issue_group"] = "criteria"
        elif code == "GRADE_EMPTY":
            issue["issue_group"] = "grades"
    issue["missing_count"] = int(issue.get("missing_count") or 1)
    return issue


def _payload_hash(payload: dict) -> str:
    serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()


def run_check_missing_data_job(*, link_id: int | None = None, class_code: str | None = None, all_active: bool = True, initiated_by=None) -> JobRun:
    links = _collect_links(link_id=link_id, class_code=class_code, all_active=all_active)
    params = {"link_id": link_id, "class_code": class_code, "all_active": all_active}
    job_run = JobRun.objects.create(
        job_type="check_missing_data",
        status=JobRun.Status.RUNNING,
        started_at=timezone.now(),
        params_json=params,
        initiated_by=initiated_by,
    )
    aggregated_issues: list[dict] = []
    telegram_status = "not_configured"
    telegram_reason = ""
    try:
        for link in links:
            temp_file: Path | None = None
            try:
                temp_file = fetch_workbook_for_link(link)
                result = validate_workbook(str(temp_file))
                for issue in result.get("issues", []):
                    if issue.get("code") in {"DESCRIPTOR_EMPTY", "CRITERIA_HEADERS_EMPTY", "GRADE_EMPTY"}:
                        aggregated_issues.append(_normalize_issue_context(issue, link))
            except Exception as exc:
                log_step(job_run=job_run, level=JobLog.Level.ERROR, message="Missing data check failed for table", context={"link_id": link.id, "reason": str(exc)})
            finally:
                if temp_file and temp_file.exists():
                    temp_file.unlink(missing_ok=True)

        job_run.result_json = {"issues": aggregated_issues}
        summary_payload = build_missing_data_summary(job_run)
        payload_hash = _payload_hash({"issues": sorted(aggregated_issues, key=lambda i: (i.get("teacher_name", ""), i.get("class_code", ""), i.get("subject_name", ""), i.get("code", ""), i.get("row") or 0, i.get("field") or ""))})
        admin_chat_id = (getattr(settings, "ADMIN_LOG_CHAT_ID", "") or "").strip()
        if not admin_chat_id:
            telegram_status = "failed"
            telegram_reason = "ADMIN_LOG_CHAT_ID is not configured"
        else:
            already_sent = NotificationEvent.objects.filter(
                job_run__job_type="check_missing_data",
                channel=NotificationEvent.Channel.TELEGRAM,
                payload_hash=payload_hash,
                status=NotificationEvent.Status.SENT,
            ).exists()
            if already_sent:
                telegram_status = "skipped_duplicate"
            else:
                try:
                    for chunk in split_summary_for_telegram(summary_payload["text"]):
                        send_telegram(admin_chat_id, chunk, job_run_id=job_run.id)
                    telegram_status = "sent"
                    NotificationEvent.objects.create(
                        job_run=job_run,
                        teacher_name="__admin_missing_data__",
                        channel=NotificationEvent.Channel.TELEGRAM,
                        status=NotificationEvent.Status.SENT,
                        payload_hash=payload_hash,
                    )
                except TelegramSendError as exc:
                    telegram_status = "failed"
                    telegram_reason = str(exc)

        job_run.result_json = {
            "summary": summary_payload,
            "issues": aggregated_issues,
            "telegram": {"status": telegram_status, "reason": telegram_reason},
        }
        if telegram_status == "failed":
            final_status = JobRun.Status.PARTIAL if aggregated_issues else JobRun.Status.FAILED
        else:
            final_status = JobRun.Status.SUCCESS
        job_run.status = final_status
        job_run.finished_at = timezone.now()
        job_run.save(update_fields=["result_json", "status", "finished_at"])
    except Exception as exc:
        job_run.status = JobRun.Status.FAILED
        job_run.finished_at = timezone.now()
        job_run.result_json = {"issues": aggregated_issues, "telegram": {"status": "failed", "reason": str(exc)}}
        job_run.save(update_fields=["status", "finished_at", "result_json"])
    return job_run