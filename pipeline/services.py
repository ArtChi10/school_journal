import logging
import re
from pathlib import Path
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

logger = logging.getLogger(__name__)

_CRITERIA_ANCHOR_RU = "критерии оценивания"
_CRITERIA_ANCHOR_EN = "assessment criteria"
_EXCLUDED_HEADER_KEYWORDS = (
    "коммент",
    "comment",
    "пересда",
    "retake",
    "resit",
    "make-up",
)


class WorkbookReadError(ValueError):
    """Raised when a workbook cannot be read for criteria extraction."""


def _normalize_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]*\|\s*", " | ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _is_tutor_sheet(sheet_name: str) -> bool:
    title = sheet_name.strip().lower()
    return "тьютор" in title or "tutor" in title


def _find_criteria_header_row(ws) -> int | None:
    for row_num in range(1, ws.max_row + 1):
        anchor = _normalize_text(ws.cell(row=row_num, column=2).value)
        if _CRITERIA_ANCHOR_RU in anchor and _CRITERIA_ANCHOR_EN in anchor:
            return row_num
    return None


def _is_excluded_header(header: object) -> bool:
    normalized = _normalize_text(header)
    return any(keyword in normalized for keyword in _EXCLUDED_HEADER_KEYWORDS)


def _parse_module_number(value: object) -> int:
    if value is None:
        return 0

    if isinstance(value, int):
        return value

    as_text = str(value).strip()
    try:
        return int(float(as_text))
    except (ValueError, TypeError):
        match = re.search(r"\d+", as_text)
        return int(match.group(0)) if match else 0


def extract_raw_criteria_from_workbook(path: str, class_code: str) -> list[dict]:
    try:
        wb = load_workbook(path, data_only=True)
    except (FileNotFoundError, InvalidFileException, BadZipFile, OSError) as exc:
        logger.error(
            "Failed to read workbook for criteria extraction: %s (%s)",
            path,
            exc.__class__.__name__,
        )
        raise WorkbookReadError(f"Cannot read workbook: {path}") from exc

    records: list[dict] = []
    source_workbook = str(Path(path))

    for sheet_name in wb.sheetnames:
        if _is_tutor_sheet(sheet_name):
            continue

        ws = wb[sheet_name]
        criteria_header_row = _find_criteria_header_row(ws)
        if criteria_header_row is None:
            continue

        subject_name = sheet_name
        teacher_name = str(ws["C2"].value or "").strip()
        module_number = _parse_module_number(ws["C3"].value)

        for col in range(3, ws.max_column + 1):
            header = ws.cell(row=criteria_header_row, column=col).value
            criterion_text = str(header or "").strip()

            if not criterion_text:
                continue
            if _is_excluded_header(header):
                continue

            records.append(
                {
                    "class_code": class_code,
                    "subject_name": subject_name,
                    "teacher_name": teacher_name,
                    "module_number": module_number,
                    "criterion_text": criterion_text,
                    "source_sheet_name": sheet_name,
                    "source_workbook": source_workbook,
                }
            )

    return records