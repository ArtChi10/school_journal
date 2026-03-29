from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from jobs.models import JobLog, JobRun
from jobs.services import log_step

GOOGLE_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_GOOGLE_DOC = "application/vnd.google-apps.document"
MIME_PDF = "application/pdf"


class PdfConversionError(RuntimeError):
    """Raised when DOCX->PDF conversion cannot continue for a file."""


def _normalize_docx_inputs(docx_files: Iterable[dict | str]) -> list[dict]:
    normalized: list[dict] = []
    for item in docx_files:
        if isinstance(item, str):
            path = Path(item)
            normalized.append(
                {
                    "path": str(path),
                    "class_code": path.parent.name,
                    "student": path.stem,
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
                "class_code": str(item.get("class_code") or path.parent.name),
                "student": str(item.get("student") or path.stem),
            }
        )

    return normalized


def _require_env_path(var_name: str) -> Path:
    raw = (os.getenv(var_name) or "").strip()
    if not raw:
        raise PdfConversionError(f"{var_name} is required for google pdf conversion mode")

    path = Path(raw)
    if not path.exists():
        raise PdfConversionError(f"{var_name} does not exist: {path}")
    return path


def _build_google_drive_service():
    mode = (os.getenv("GOOGLE_ACCESS_MODE") or "oauth_owner").strip().lower()
    if mode not in {"oauth_owner", "service_account"}:
        raise PdfConversionError("GOOGLE_ACCESS_MODE must be oauth_owner or service_account")

    from googleapiclient.discovery import build

    if mode == "oauth_owner":
        token_path = _require_env_path("GOOGLE_OAUTH_TOKEN_PATH")
        _require_env_path("GOOGLE_OAUTH_CLIENT_SECRET_PATH")

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(token_path), GOOGLE_DRIVE_SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise PdfConversionError("OAuth token is invalid and cannot be refreshed")
    else:
        creds_path = _require_env_path("GOOGLE_SERVICE_ACCOUNT_JSON_PATH")
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(str(creds_path), scopes=GOOGLE_DRIVE_SCOPES)

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _resolve_local_converter_bin() -> str:
    configured = (os.getenv("LIBREOFFICE_BIN") or "").strip()
    candidate = configured or "libreoffice"

    if Path(candidate).is_absolute():
        if not Path(candidate).exists():
            raise PdfConversionError(f"LibreOffice binary does not exist: {candidate}")
        return candidate

    resolved = shutil.which(candidate)
    if not resolved:
        raise PdfConversionError(
            "LibreOffice converter not found. Install LibreOffice or switch PDF_CONVERT_MODE=google"
        )
    return resolved


def _convert_docx_local(*, docx_path: Path, pdf_path: Path) -> None:
    libreoffice_bin = _resolve_local_converter_bin()

    with tempfile.TemporaryDirectory(prefix="pdf_local_") as tmpdir:
        tmp_out = Path(tmpdir)
        command = [
            libreoffice_bin,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_out),
            str(docx_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            details = stderr or stdout or "unknown local conversion error"
            raise PdfConversionError(f"LibreOffice conversion failed: {details}")

        generated_pdf = tmp_out / f"{docx_path.stem}.pdf"
        if not generated_pdf.exists():
            raise PdfConversionError(f"Converted PDF not found after local conversion: {generated_pdf}")

        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(generated_pdf), str(pdf_path))


def _convert_docx_google(*, docx_path: Path, pdf_path: Path) -> None:
    service = _build_google_drive_service()

    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(str(docx_path), mimetype=MIME_DOCX, resumable=False)
    created = (
        service.files()
        .create(
            body={"name": docx_path.name, "mimeType": MIME_GOOGLE_DOC},
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        )
        .execute()
    )

    file_id = created["id"]
    try:
        pdf_bytes = service.files().export(fileId=file_id, mimeType=MIME_PDF).execute()
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(io.BytesIO(pdf_bytes).getvalue())
    finally:
        service.files().delete(fileId=file_id, supportsAllDrives=True).execute()


def run_convert_docx_to_pdf_step(
    *,
    docx_files: Iterable[dict | str],
    job_run: JobRun | None = None,
) -> dict:
    files = _normalize_docx_inputs(docx_files)
    base_mode = (os.getenv("PDF_CONVERT_MODE") or "local").strip().lower()
    output_root = Path((os.getenv("PDF_OUTPUT_ROOT") or "output/pdf").strip())

    if base_mode not in {"local", "google"}:
        raise PdfConversionError("PDF_CONVERT_MODE must be either 'local' or 'google'")

    pdf_success = 0
    pdf_failed = 0
    pdf_files: list[dict] = []
    errors: list[dict] = []

    for entry in files:
        docx_path = Path(entry["path"])
        class_code = str(entry["class_code"])
        student = str(entry["student"])
        pdf_path = output_root / class_code / f"{docx_path.stem}.pdf"
        mode_used = base_mode

        try:
            if not docx_path.exists():
                raise FileNotFoundError(f"DOCX file not found: {docx_path}")

            if base_mode == "local":
                try:
                    _convert_docx_local(docx_path=docx_path, pdf_path=pdf_path)
                except Exception as exc:  # noqa: BLE001
                    mode_used = "google"
                    try:
                        _convert_docx_google(docx_path=docx_path, pdf_path=pdf_path)
                    except Exception as google_exc:  # noqa: BLE001
                        raise PdfConversionError(
                            f"Local conversion failed ({exc}); google fallback failed ({google_exc})"
                        ) from google_exc
            else:
                _convert_docx_google(docx_path=docx_path, pdf_path=pdf_path)

            pdf_success += 1
            item = {"class_code": class_code, "student": student, "path": str(pdf_path)}
            pdf_files.append(item)

            if job_run:
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.INFO,
                    message="DOCX converted to PDF",
                    context={
                        "docx_input": str(docx_path),
                        "pdf_output": str(pdf_path),
                        "mode": mode_used,
                    },
                )
        except Exception as exc:  # noqa: BLE001
            pdf_failed += 1
            error = {
                "class_code": class_code,
                "student": student,
                "docx_input": str(docx_path),
                "pdf_output": str(pdf_path),
                "mode": mode_used,
                "error": str(exc),
                "type": exc.__class__.__name__,
            }
            errors.append(error)
            if job_run:
                log_step(
                    job_run=job_run,
                    level=JobLog.Level.ERROR,
                    message=f"DOCX->PDF conversion failed: {exc}",
                    context=error,
                )

    return {
        "pdf_total": len(files),
        "pdf_success": pdf_success,
        "pdf_failed": pdf_failed,
        "pdf_files": pdf_files,
        "errors": errors,
    }