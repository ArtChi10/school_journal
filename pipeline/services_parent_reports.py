from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from django.core.mail import EmailMessage

from jobs.models import JobLog, JobRun
from jobs.services import log_step
from notifications.models import NotificationEvent


class ParentReportSendError(RuntimeError):
    """Raised when parent report sending input is invalid."""


def _clean_str(value: object) -> str:
    return str(value or "").strip()


def _normalize_pdf_entries(pdf_files: Iterable[dict | str]) -> list[dict]:
    normalized: list[dict] = []
    for item in pdf_files:
        if isinstance(item, str):
            path = Path(item)
            normalized.append(
                {
                    "student": path.stem,
                    "class_code": path.parent.name,
                    "path": str(path),
                }
            )
            continue

        raw_path = _clean_str(item.get("path"))
        if not raw_path:
            continue
        path = Path(raw_path)
        normalized.append(
            {
                "student": _clean_str(item.get("student")) or path.stem,
                "class_code": _clean_str(item.get("class_code")) or path.parent.name,
                "path": str(path),
            }
        )
    return normalized


def _normalize_recipients(raw: object) -> list[dict]:
    normalized: list[dict] = []
    if not raw:
        return normalized

    if isinstance(raw, str):
        value = _clean_str(raw)
        if value:
            normalized.append({"channel": "email", "value": value})
        return normalized

    if isinstance(raw, dict):
        channel = _clean_str(raw.get("channel") or "email").lower()
        value = _clean_str(raw.get("value") or raw.get("email") or raw.get("chat_id"))
        if value:
            normalized.append({"channel": channel, "value": value})
        return normalized

    if isinstance(raw, list):
        for entry in raw:
            normalized.extend(_normalize_recipients(entry))
        return normalized

    return normalized


def _normalize_contacts(contacts: Iterable[dict]) -> list[dict]:
    normalized: list[dict] = []
    for item in contacts:
        student = _clean_str(item.get("student"))
        if not student:
            continue
        normalized.append(
            {
                "student": student,
                "class_code": _clean_str(item.get("class_code")),
                "recipients": _normalize_recipients(item.get("recipients") or item.get("contacts") or item.get("email")),
            }
        )
    return normalized


def _student_key(class_code: str, student: str) -> tuple[str, str]:
    return (class_code.casefold(), student.casefold())


def _find_pdf(pdf_by_key: dict[tuple[str, str], dict], *, class_code: str, student: str) -> dict | None:
    if class_code:
        exact = pdf_by_key.get(_student_key(class_code, student))
        if exact:
            return exact

    for (_, student_key), pdf in pdf_by_key.items():
        if student_key == student.casefold() and (not class_code or pdf["class_code"].casefold() == class_code.casefold()):
            return pdf
    return None


def _payload_hash(*, class_code: str, student: str, recipient: str, channel: str, pdf_path: str) -> str:
    payload = f"{class_code}|{student}|{channel}|{recipient}|{pdf_path}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def run_send_parent_reports_step(
    *,
    pdf_files: Iterable[dict | str],
    contacts: Iterable[dict],
    job_run: JobRun | None = None,
    email_subject_template: str = "Отчёт ученика: {student}",
    email_body_template: str = "Здравствуйте! Во вложении отчёт ученика {student} ({class_code}).",
) -> dict:
    normalized_pdfs = _normalize_pdf_entries(pdf_files)
    normalized_contacts = _normalize_contacts(contacts)

    pdf_by_key = {_student_key(item["class_code"], item["student"]): item for item in normalized_pdfs}

    students_total = len(normalized_contacts)
    sent_success = 0
    sent_failed = 0
    skipped_no_contact = 0
    skipped_no_pdf = 0
    repeated_skipped = 0
    details: list[dict] = []

    for contact in normalized_contacts:
        student = contact["student"]
        class_code = contact["class_code"]
        recipients = contact["recipients"]

        if not recipients:
            skipped_no_contact += 1
            detail = {
                "student": student,
                "class_code": class_code,
                "recipient": None,
                "status": "skipped_no_contact",
                "error": "No recipients found for student",
            }
            details.append(detail)
            if job_run:
                log_step(job_run=job_run, level=JobLog.Level.WARNING, message="Parent report skipped: no contact", context=detail)
            continue

        pdf_entry = _find_pdf(pdf_by_key, class_code=class_code, student=student)
        if not pdf_entry:
            skipped_no_pdf += 1
            detail = {
                "student": student,
                "class_code": class_code,
                "recipient": None,
                "status": "skipped_no_pdf",
                "error": "Prepared PDF not found",
            }
            details.append(detail)
            if job_run:
                log_step(job_run=job_run, level=JobLog.Level.ERROR, message="Parent report skipped: PDF not found", context=detail)
            continue

        pdf_path = Path(pdf_entry["path"])
        if not pdf_path.exists():
            skipped_no_pdf += 1
            detail = {
                "student": student,
                "class_code": class_code,
                "recipient": None,
                "status": "skipped_no_pdf",
                "error": f"Prepared PDF not found on disk: {pdf_path}",
            }
            details.append(detail)
            if job_run:
                log_step(job_run=job_run, level=JobLog.Level.ERROR, message="Parent report skipped: PDF missing on disk", context=detail)
            continue

        for recipient in recipients:
            channel = _clean_str(recipient.get("channel") or "email").lower()
            target = _clean_str(recipient.get("value"))
            event_hash = _payload_hash(
                class_code=pdf_entry["class_code"],
                student=student,
                recipient=target,
                channel=channel,
                pdf_path=str(pdf_path),
            )

            if NotificationEvent.objects.filter(
                teacher_name=student,
                channel=channel,
                payload_hash=event_hash,
                status=NotificationEvent.Status.SENT,
            ).exists():
                repeated_skipped += 1
                detail = {
                    "student": student,
                    "class_code": pdf_entry["class_code"],
                    "recipient": target,
                    "status": "duplicate_skipped",
                    "error": "Already sent earlier (same payload hash)",
                }
                details.append(detail)
                if job_run:
                    log_step(job_run=job_run, level=JobLog.Level.INFO, message="Parent report duplicate skipped", context=detail)
                continue

            try:
                if channel != "email":
                    raise ParentReportSendError(f"Unsupported channel for PDF delivery: {channel}")

                subject = email_subject_template.format(student=student, class_code=pdf_entry["class_code"])
                body = email_body_template.format(student=student, class_code=pdf_entry["class_code"])
                message = EmailMessage(subject=subject, body=body, to=[target])
                message.attach_file(str(pdf_path), mimetype="application/pdf")
                message.send(fail_silently=False)

                sent_success += 1
                if job_run:
                    NotificationEvent.objects.create(
                        job_run=job_run,
                        teacher_name=student,
                        channel=NotificationEvent.Channel.EMAIL,
                        status=NotificationEvent.Status.SENT,
                        payload_hash=event_hash,
                    )
                detail = {
                    "student": student,
                    "class_code": pdf_entry["class_code"],
                    "recipient": target,
                    "status": "sent_success",
                    "error": None,
                }
                details.append(detail)
                if job_run:
                    log_step(job_run=job_run, level=JobLog.Level.INFO, message="Parent report sent", context=detail)
            except Exception as exc:  # noqa: BLE001
                sent_failed += 1
                if job_run:
                    NotificationEvent.objects.create(
                        job_run=job_run,
                        teacher_name=student,
                        channel=NotificationEvent.Channel.EMAIL if channel == "email" else channel,
                        status=NotificationEvent.Status.ERROR,
                        payload_hash=event_hash,
                    )
                detail = {
                    "student": student,
                    "class_code": pdf_entry["class_code"],
                    "recipient": target,
                    "status": "sent_failed",
                    "error": str(exc),
                }
                details.append(detail)
                if job_run:
                    log_step(job_run=job_run, level=JobLog.Level.ERROR, message="Parent report send failed", context=detail)

    return {
        "students_total": students_total,
        "sent_success": sent_success,
        "sent_failed": sent_failed,
        "skipped_no_contact": skipped_no_contact,
        "skipped_no_pdf": skipped_no_pdf,
        "repeated_skipped": repeated_skipped,
        "details": details,
    }