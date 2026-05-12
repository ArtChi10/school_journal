from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlparse

from admin_panel.google_oauth import (
    GOOGLE_OAUTH_UPLOAD_SCOPES,
    get_google_oauth_client_secret_path,
    get_google_oauth_token_path,
)
from jobs.models import JobLog, JobRun
from jobs.services import log_step

GOOGLE_UPLOAD_SCOPES = GOOGLE_OAUTH_UPLOAD_SCOPES


class ReviewUploadError(RuntimeError):
    """Raised when review folder upload configuration/execution fails."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


_DRIVE_FOLDER_RE = re.compile(r"/folders/([a-zA-Z0-9_-]+)")


def _require_env_path(var_name: str) -> Path:
    raw = (os.getenv(var_name) or "").strip()
    if not raw:
        raise ReviewUploadError("invalid_config", f"{var_name} is required")

    path = Path(raw)
    if not path.exists():
        raise ReviewUploadError("invalid_config", f"{var_name} file does not exist: {path}")
    return path


def _parse_folder_mapping(raw_mapping: str | None) -> dict[str, str]:
    if not raw_mapping:
        return {}

    mapping: dict[str, str] = {}
    for part in raw_mapping.split(","):
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise ReviewUploadError(
                "invalid_config",
                "GOOGLE_REVIEW_FOLDER_MAP format must be 'CLASS:FOLDER_ID,CLASS2:FOLDER_ID2'",
            )
        class_code, folder_id = item.split(":", 1)
        class_code = class_code.strip()
        folder_id = folder_id.strip()
        if not class_code or not folder_id:
            raise ReviewUploadError(
                "invalid_config",
                "GOOGLE_REVIEW_FOLDER_MAP contains empty class_code or folder_id",
            )
        mapping[class_code] = folder_id
    return mapping


def resolve_review_folder_id(class_code: str) -> str:
    folder_map = _parse_folder_mapping(os.getenv("GOOGLE_REVIEW_FOLDER_MAP"))
    if class_code in folder_map:
        return folder_map[class_code]

    default_folder = (os.getenv("GOOGLE_REVIEW_FOLDER_ID") or "").strip()
    if default_folder:
        return default_folder

    raise ReviewUploadError(
        "invalid_config",
        "Set GOOGLE_REVIEW_FOLDER_ID or GOOGLE_REVIEW_FOLDER_MAP for DOCX review uploads",
    )


def extract_drive_folder_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise ReviewUploadError("invalid_config", "Google Drive folder URL is required")

    folder_match = _DRIVE_FOLDER_RE.search(raw)
    if folder_match:
        return folder_match.group(1)

    parsed = urlparse(raw)
    query_id = parse_qs(parsed.query).get("id", [None])[0]
    if query_id:
        return query_id

    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", raw):
        return raw

    raise ReviewUploadError("invalid_config", f"Could not extract Google Drive folder id from: {raw}")


def _build_drive_service():
    mode = (os.getenv("GOOGLE_ACCESS_MODE") or "oauth_owner").strip().lower()
    if mode not in {"oauth_owner", "service_account"}:
        raise ReviewUploadError(
            "invalid_mode",
            "DOCX upload supports only GOOGLE_ACCESS_MODE=oauth_owner or service_account",
        )

    from googleapiclient.discovery import build

    if mode == "oauth_owner":
        token_path = get_google_oauth_token_path()
        client_secret_path = get_google_oauth_client_secret_path()
        if not token_path.exists():
            raise ReviewUploadError("invalid_config", f"GOOGLE_OAUTH_TOKEN_PATH file does not exist: {token_path}")
        if not client_secret_path.exists():
            raise ReviewUploadError(
                "invalid_config",
                f"GOOGLE_OAUTH_CLIENT_SECRET_PATH file does not exist: {client_secret_path}",
            )

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(token_path))
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise ReviewUploadError("invalid_config", "OAuth token is invalid and cannot be refreshed")
    else:
        creds_path = _require_env_path("GOOGLE_SERVICE_ACCOUNT_JSON_PATH")
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(str(creds_path), scopes=GOOGLE_UPLOAD_SCOPES)

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_existing_file(service, *, name: str, parent_id: str) -> dict | None:
    safe_name = name.replace("'", "\\'")
    query = f"name = '{safe_name}' and '{parent_id}' in parents and trashed = false"
    response = (
        service.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id,name,webViewLink)",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            pageSize=1,
        )
        .execute()
    )
    items = response.get("files", [])
    return items[0] if items else None


def _upload_or_update_file(service, *, local_path: Path, folder_id: str, duplicate_strategy: str) -> tuple[str, str]:
    from googleapiclient.http import MediaFileUpload

    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    media = MediaFileUpload(str(local_path), mimetype=mime, resumable=False)

    existing = _find_existing_file(service, name=local_path.name, parent_id=folder_id)
    if existing and duplicate_strategy == "update":
        result = (
            service.files()
            .update(
                fileId=existing["id"],
                media_body=media,
                fields="id,webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        return result["id"], result.get("webViewLink", "")

    if existing and duplicate_strategy == "skip":
        return existing["id"], existing.get("webViewLink", "")

    meta = {"name": local_path.name, "parents": [folder_id]}
    result = (
        service.files()
        .create(
            body=meta,
            media_body=media,
            fields="id,webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )
    return result["id"], result.get("webViewLink", "")


def _upload_or_update_file_with_action(
    service,
    *,
    local_path: Path,
    folder_id: str,
    duplicate_strategy: str,
) -> tuple[str, str, str]:
    from googleapiclient.http import MediaFileUpload

    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    media = MediaFileUpload(str(local_path), mimetype=mime, resumable=False)

    existing = _find_existing_file(service, name=local_path.name, parent_id=folder_id)
    if existing and duplicate_strategy == "update":
        result = (
            service.files()
            .update(
                fileId=existing["id"],
                media_body=media,
                fields="id,webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        return result["id"], result.get("webViewLink", ""), "updated"

    if existing and duplicate_strategy == "skip":
        return existing["id"], existing.get("webViewLink", ""), "skipped"

    meta = {"name": local_path.name, "parents": [folder_id]}
    result = (
        service.files()
        .create(
            body=meta,
            media_body=media,
            fields="id,webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )
    return result["id"], result.get("webViewLink", ""), "created"


def _normalize_docx_inputs(docx_files: Iterable[dict | str]) -> list[dict]:
    normalized: list[dict] = []

    for item in docx_files:
        if isinstance(item, str):
            path = Path(item)
            class_code = path.parent.name
            normalized.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "class_code": class_code,
                }
            )
            continue

        raw_path = str(item.get("path") or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path)
        normalized.append(
            {
                "path": str(path),
                "name": str(item.get("name") or path.name),
                "class_code": str(item.get("class_code") or path.parent.name),
            }
        )

    return normalized


def run_upload_docx_review_step(
    *,
    docx_files: Iterable[dict | str],
    job_run: JobRun | None = None,
) -> dict:
    files = _normalize_docx_inputs(docx_files)
    uploaded_success = 0
    uploaded_failed = 0
    uploaded_files: list[dict] = []
    errors: list[dict] = []

    duplicate_strategy = (os.getenv("GOOGLE_REVIEW_DUPLICATE_STRATEGY") or "update").strip().lower()
    if duplicate_strategy not in {"update", "skip"}:
        raise ReviewUploadError(
            "invalid_config",
            "GOOGLE_REVIEW_DUPLICATE_STRATEGY must be either 'update' or 'skip'",
        )

    service = _build_drive_service()

    for entry in files:
        path = Path(entry["path"])
        class_code = str(entry["class_code"])

        try:
            folder_id = resolve_review_folder_id(class_code)
            if job_run:
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.INFO,
                    message="Review upload started",
                    context={
                        "name": entry["name"],
                        "class_code": class_code,
                        "path": str(path),
                        "folder_id": folder_id,
                        "duplicate_strategy": duplicate_strategy,
                    },
                )

            if not path.exists():
                raise FileNotFoundError(f"DOCX file not found: {path}")

            file_id, link = _upload_or_update_file(
                service,
                local_path=path,
                folder_id=folder_id,
                duplicate_strategy=duplicate_strategy,
            )
            uploaded_success += 1
            uploaded_files.append(
                {
                    "name": entry["name"],
                    "class_code": class_code,
                    "drive_file_id": file_id,
                    "link": link,
                }
            )

            if job_run:
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.INFO,
                    message="Review upload succeeded",
                    context={
                        "name": entry["name"],
                        "class_code": class_code,
                        "drive_file_id": file_id,
                        "link": link,
                    },
                )
        except Exception as exc:  # noqa: BLE001
            uploaded_failed += 1
            error = {
                "name": entry["name"],
                "class_code": class_code,
                "error": str(exc),
                "type": exc.__class__.__name__,
            }
            errors.append(error)
            if job_run:
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.ERROR,
                    message=f"Review upload failed: {exc}",
                    context=error,
                )

    return {
        "uploaded_total": len(files),
        "uploaded_success": uploaded_success,
        "uploaded_failed": uploaded_failed,
        "uploaded_files": uploaded_files,
        "errors": errors,
    }


def upload_docx_files_to_drive_folder(
    *,
    docx_files: Iterable[dict | str],
    folder_id: str,
    job_run: JobRun | None = None,
    duplicate_strategy: str = "update",
) -> dict:
    files = _normalize_docx_inputs(docx_files)
    strategy = (duplicate_strategy or "update").strip().lower()
    if strategy not in {"update", "skip"}:
        raise ReviewUploadError("invalid_config", "duplicate_strategy must be either 'update' or 'skip'")

    service = _build_drive_service()
    uploaded_success = 0
    uploaded_failed = 0
    uploaded_created = 0
    uploaded_updated = 0
    uploaded_skipped = 0
    uploaded_files: list[dict] = []
    errors: list[dict] = []

    for entry in files:
        path = Path(entry["path"])
        try:
            if job_run:
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.INFO,
                    message="DOCX upload to review folder started",
                    context={"name": entry["name"], "path": str(path), "folder_id": folder_id},
                )

            if not path.exists():
                raise FileNotFoundError(f"DOCX file not found: {path}")

            file_id, link, action = _upload_or_update_file_with_action(
                service,
                local_path=path,
                folder_id=folder_id,
                duplicate_strategy=strategy,
            )
            uploaded_success += 1
            if action == "created":
                uploaded_created += 1
                message = "DOCX uploaded to Drive"
            elif action == "updated":
                uploaded_updated += 1
                message = "Existing Drive DOCX updated"
            else:
                uploaded_skipped += 1
                message = "Existing Drive DOCX skipped"

            payload = {
                "name": path.name,
                "class_code": entry["class_code"],
                "drive_file_id": file_id,
                "link": link,
                "action": action,
            }
            uploaded_files.append(payload)
            if job_run:
                log_step(job_run=job_run, level=JobLog.Level.INFO, message=message, context=payload)
        except Exception as exc:  # noqa: BLE001
            uploaded_failed += 1
            error = {
                "name": entry["name"],
                "class_code": entry["class_code"],
                "error": str(exc),
                "type": exc.__class__.__name__,
            }
            errors.append(error)
            if job_run:
                log_step(job_run=job_run, level=JobLog.Level.ERROR, message="DOCX upload to Drive failed", context=error)

    return {
        "uploaded_total": len(files),
        "uploaded_success": uploaded_success,
        "uploaded_failed": uploaded_failed,
        "uploaded_created": uploaded_created,
        "uploaded_updated": uploaded_updated,
        "uploaded_skipped": uploaded_skipped,
        "uploaded_files": uploaded_files,
        "errors": errors,
    }
