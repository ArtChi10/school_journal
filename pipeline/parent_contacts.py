from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from pipeline.models import ParentContact


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _clean(value: object) -> str:
    return str(value or "").strip()


def _validate_optional_email(value: str) -> bool:
    if not value:
        return True
    try:
        validate_email(value)
        return True
    except ValidationError:
        return False


def import_parent_contacts_csv(content: bytes) -> ImportResult:
    payload = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(payload))
    result = ImportResult()

    rows = list(reader)
    if not rows:
        return result

    start_index = 0
    first_cell = _clean(rows[0][0] if rows[0] else "")
    if first_cell.lower() in {"parallel", "параллель"}:
        start_index = 1

    for idx, row in enumerate(rows[start_index:], start=start_index + 1):
        if not any(_clean(cell) for cell in row):
            result.skipped += 1
            continue

        parallel_raw = _clean(row[0] if len(row) > 0 else "")
        student_name = _clean(row[1] if len(row) > 1 else "")
        email_1 = _clean(row[2] if len(row) > 2 else "")
        email_2 = _clean(row[3] if len(row) > 3 else "")

        if not parallel_raw.isdigit() or not student_name:
            result.errors.append(f"Строка {idx}: заполните параллель (число) и ФИО ученика")
            continue

        if not _validate_optional_email(email_1) or not _validate_optional_email(email_2):
            result.errors.append(f"Строка {idx}: некорректный email")
            continue

        parallel = int(parallel_raw)
        _, created = ParentContact.objects.update_or_create(
            parallel=parallel,
            student_name=student_name,
            defaults={
                "parent_email_1": email_1,
                "parent_email_2": email_2,
                "is_active": True,
            },
        )
        if created:
            result.created += 1
        else:
            result.updated += 1

    return result


def parent_contacts_to_pipeline_payload() -> list[dict]:
    payload: list[dict] = []
    contacts = ParentContact.objects.filter(is_active=True)
    for entry in contacts:
        recipients = []
        if entry.parent_email_1:
            recipients.append({"channel": "email", "value": entry.parent_email_1})
        if entry.parent_email_2:
            recipients.append({"channel": "email", "value": entry.parent_email_2})

        payload.append(
            {
                "class_code": _clean(entry.class_code),
                "student": entry.student_name,
                "recipients": recipients,
            }
        )
    return payload