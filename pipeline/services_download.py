from __future__ import annotations

import os
import re
import socket
import tempfile
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from django.utils import timezone

from admin_panel.google_oauth import (
    GOOGLE_OAUTH_DOWNLOAD_SCOPES,
    get_google_oauth_client_secret_path,
    get_google_oauth_token_path,
)
from jobs.models import JobLog, JobRun
from jobs.services import log_step
from journal_links.models import ClassSheetLink

GOOGLE_ACCESS_MODE_PUBLIC = "public_link"
GOOGLE_ACCESS_MODE_OAUTH_OWNER = "oauth_owner"
GOOGLE_ACCESS_MODE_SERVICE_ACCOUNT = "service_account"
GOOGLE_ACCESS_MODE_DEFAULT = GOOGLE_ACCESS_MODE_OAUTH_OWNER
_GOOGLE_SHEET_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


class DescriptorDownloadError(RuntimeError):
    """Raised when descriptor workbook download fails."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def get_google_access_mode() -> str:
    mode = os.getenv("GOOGLE_ACCESS_MODE", GOOGLE_ACCESS_MODE_DEFAULT).strip().lower()
    if mode not in {
        GOOGLE_ACCESS_MODE_PUBLIC,
        GOOGLE_ACCESS_MODE_OAUTH_OWNER,
        GOOGLE_ACCESS_MODE_SERVICE_ACCOUNT,
    }:
        raise DescriptorDownloadError(
            "invalid_mode",
            "Invalid GOOGLE_ACCESS_MODE value "
            f"'{mode}'. Allowed: {GOOGLE_ACCESS_MODE_PUBLIC}|{GOOGLE_ACCESS_MODE_OAUTH_OWNER}|{GOOGLE_ACCESS_MODE_SERVICE_ACCOUNT}.",
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
        raise DescriptorDownloadError("invalid_url", f"Could not extract file id from URL: {url}")

    export_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
    gid = _extract_gid(url)
    if gid:
        export_url = f"{export_url}&gid={gid}"
    return export_url


def _require_env_path(var_name: str) -> Path:
    raw = (os.getenv(var_name) or "").strip()
    if not raw:
        raise DescriptorDownloadError("invalid_config", f"{var_name} is required")

    path = Path(raw)
    if not path.exists():
        raise DescriptorDownloadError("invalid_config", f"{var_name} file does not exist: {path}")

    return path


def _map_http_error(exc: HTTPError) -> DescriptorDownloadError:
    if exc.code in {401, 403}:
        return DescriptorDownloadError(str(exc.code), f"HTTP {exc.code}: unauthorized access")
    return DescriptorDownloadError("http_error", f"HTTP {exc.code}")


def _download_public_link(url: str) -> bytes:
    export_url = _build_export_url(url)
    try:
        with urlopen(export_url, timeout=30) as response:
            return response.read()
    except HTTPError as exc:
        raise _map_http_error(exc) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise DescriptorDownloadError("timeout", "Public download timed out") from exc
    except URLError as exc:
        raise DescriptorDownloadError("network", f"Public download failed: {exc.reason}") from exc


def _download_oauth_owner(url: str) -> bytes:
    token_path = get_google_oauth_token_path()
    client_secret_path = get_google_oauth_client_secret_path()
    if not token_path.exists():
        raise DescriptorDownloadError("invalid_config", f"GOOGLE_OAUTH_TOKEN_PATH file does not exist: {token_path}")
    if not client_secret_path.exists():
        raise DescriptorDownloadError(
            "invalid_config",
            f"GOOGLE_OAUTH_CLIENT_SECRET_PATH file does not exist: {client_secret_path}",
        )

    from google.auth.transport.requests import Request
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(token_path), GOOGLE_OAUTH_DOWNLOAD_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise DescriptorDownloadError("invalid_config", "OAuth token is invalid and cannot be refreshed")

    export_url = _build_export_url(url)
    session = AuthorizedSession(creds)
    response = session.get(export_url, timeout=30)
    if response.status_code >= 400:
        if response.status_code in {401, 403}:
            raise DescriptorDownloadError(str(response.status_code), f"HTTP {response.status_code}: unauthorized access")
        raise DescriptorDownloadError("http_error", f"OAuth download failed HTTP {response.status_code}")

    return response.content


def _download_service_account(url: str) -> bytes:
    creds_path = _require_env_path("GOOGLE_SERVICE_ACCOUNT_JSON_PATH")

    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(str(creds_path), scopes=GOOGLE_OAUTH_SCOPES)

    export_url = _build_export_url(url)
    session = AuthorizedSession(creds)
    response = session.get(export_url, timeout=30)
    if response.status_code >= 400:
        if response.status_code in {401, 403}:
            raise DescriptorDownloadError(str(response.status_code), f"HTTP {response.status_code}: unauthorized access")
        raise DescriptorDownloadError("http_error", f"Service-account download failed HTTP {response.status_code}")

    return response.content


def _download_bytes(url: str, mode: str) -> bytes:
    if mode == GOOGLE_ACCESS_MODE_PUBLIC:
        return _download_public_link(url)
    if mode == GOOGLE_ACCESS_MODE_OAUTH_OWNER:
        return _download_oauth_owner(url)
    if mode == GOOGLE_ACCESS_MODE_SERVICE_ACCOUNT:
        return _download_service_account(url)
    raise DescriptorDownloadError("invalid_mode", f"Unsupported mode: {mode}")


def _resolve_links(links: Iterable[ClassSheetLink] | None, class_code: str | None) -> list[ClassSheetLink]:
    if links is not None:
        return list(links)

    queryset = ClassSheetLink.objects.filter(is_active=True)
    if class_code:
        queryset = queryset.filter(class_code=class_code)
    return list(queryset.order_by("id"))


def run_download_descriptors_step(
    *,
    links: Iterable[ClassSheetLink] | None = None,
    class_code: str | None = None,
    job_run: JobRun | None = None,
) -> dict:
    selected_links = _resolve_links(links, class_code)
    files: list[dict] = []
    success_count = 0
    failed_count = 0
    access_mode = get_google_access_mode()

    for link in selected_links:
        if job_run:
            log_step(
                job_run=job_run,
                level=JobLog.Level.INFO,
                message="Download started",
                context={"link_id": link.id, "class_code": link.class_code, "mode": access_mode},
            )

        try:
            data = _download_bytes(link.google_sheet_url, access_mode)
        except DescriptorDownloadError as exc:
            if access_mode in {GOOGLE_ACCESS_MODE_OAUTH_OWNER, GOOGLE_ACCESS_MODE_SERVICE_ACCOUNT}:
                try:
                    data = _download_public_link(link.google_sheet_url)
                    if job_run:
                        log_step(
                            job_run=job_run,
                            level=JobLog.Level.WARNING,
                            message="Private mode failed, fallback to public_link succeeded",
                            context={"link_id": link.id, "class_code": link.class_code, "error": str(exc)},
                        )
                except DescriptorDownloadError as fallback_exc:
                    failed_count += 1
                    files.append(
                        {
                            "link_id": link.id,
                            "class_code": link.class_code,
                            "subject_name": link.subject_name,
                            "status": "failed",
                            "error": str(fallback_exc),
                            "error_code": fallback_exc.category,
                        }
                    )
                    if job_run:
                        log_step(
                            job_run=job_run,
                            level=JobLog.Level.ERROR,
                            message=f"Download failed: {fallback_exc}",
                            context={
                                "link_id": link.id,
                                "class_code": link.class_code,
                                "error_code": fallback_exc.category,
                            },
                        )
                    continue
            else:
                failed_count += 1
                files.append(
                    {
                        "link_id": link.id,
                        "class_code": link.class_code,
                        "subject_name": link.subject_name,
                        "status": "failed",
                        "error": str(exc),
                        "error_code": exc.category,
                    }
                )
                if job_run:
                    log_step(
                        job_run=job_run,
                        level=JobLog.Level.ERROR,
                        message=f"Download failed: {exc}",
                        context={"link_id": link.id, "class_code": link.class_code, "error_code": exc.category},
                    )
                continue
        except Exception as exc:
            failed_count += 1
            files.append(
                {
                    "link_id": link.id,
                    "class_code": link.class_code,
                    "subject_name": link.subject_name,
                    "status": "failed",
                    "error": str(exc),
                    "error_code": "unknown_error",
                }
            )
            if job_run:
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.ERROR,
                    message=f"Download failed: {exc}",
                    context={"link_id": link.id, "class_code": link.class_code, "error_code": "unknown_error"},
                )
            continue

        with tempfile.NamedTemporaryFile(prefix="descriptor_", suffix=".xlsx", delete=False) as tmp_file:
            tmp_file.write(data)
            path = Path(tmp_file.name)

        size_bytes = path.stat().st_size
        success_count += 1
        files.append(
            {
                "link_id": link.id,
                "class_code": link.class_code,
                "subject_name": link.subject_name,
                "status": "success",
                "path": str(path),
                "size_bytes": size_bytes,
                "downloaded_at": timezone.now().isoformat(),
            }
        )
        if job_run:
            log_step(
                job_run=job_run,
                level=JobLog.Level.INFO,
                message="Download succeeded",
                context={
                    "link_id": link.id,
                    "class_code": link.class_code,
                    "path": str(path),
                    "size_bytes": size_bytes,
                },
            )

    return {
        "downloads_total": len(selected_links),
        "downloads_success": success_count,
        "downloads_failed": failed_count,
        "files": files,
    }
