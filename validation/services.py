from dataclasses import asdict, dataclass
from typing import Any

from openpyxl import load_workbook

from .rules import (
    ALLOWED_DESCRIPTOR_VALUES,
    COMMENT_REQUIRED_IF_LOW_SCORE,
    LOW_SCORE_THRESHOLD,
    RETAKE_REQUIRED_IF_LOW_SCORE,
    TEST_SCORE_MAX,
    TEST_SCORE_MIN,
)


@dataclass
class ValidationIssue:
    code: str
    severity: str  # critical | warning | info
    sheet: str
    row: int | None
    student: str | None
    field: str | None
    message: str


def _is_empty(v: Any) -> bool:
    return v is None or str(v).strip() == ""


def validate_workbook(path: str) -> dict:
    wb = load_workbook(path, data_only=True)
    issues: list[ValidationIssue] = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        issues.extend(validate_sheet(ws, sheet_name))

    summary = {
        "total": len(issues),
        "critical": sum(1 for i in issues if i.severity == "critical"),
        "warning": sum(1 for i in issues if i.severity == "warning"),
        "info": sum(1 for i in issues if i.severity == "info"),
    }

    return {
        "summary": summary,
        "issues": [asdict(i) for i in issues],
    }


def validate_sheet(ws, sheet_name: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    # MVP-упрощение:
    # строка критериев = 5, ученики с 7-й (как в ваших таблицах)
    criteria_row = 5
    student_start_row = 7

    # Найдём колонки:
    # A имя, B фамилия, C.. критерии, далее тесты, комментарий, пересдача
    max_col = ws.max_column

    # Пытаемся найти столбцы "Комментарий"/"Пересдача" по заголовку строки criteria_row
    comment_col = None
    retake_col = None
    test_cols = []

    for col in range(1, max_col + 1):
        hdr = ws.cell(row=criteria_row, column=col).value
        h = str(hdr).strip().lower() if hdr else ""

        if "коммент" in h or "comment" in h:
            comment_col = col
        elif "пересда" in h or "retake" in h or "resit" in h:
            retake_col = col
        elif "квиз" in h or "тест" in h or "quiz" in h or "test" in h:
            test_cols.append(col)

    # Пробег по ученикам
    row = student_start_row
    while row <= ws.max_row:
        first = ws.cell(row=row, column=1).value
        last = ws.cell(row=row, column=2).value

        # конец списка учеников
        if _is_empty(first) and _is_empty(last):
            row += 1
            continue

        student_name = f"{first or ''} {last or ''}".strip()

        # 1) Проверка дескрипторных ячеек (грубая MVP-логика):
        # считаем критериями диапазон C..(до первой test/comment/retake колонки)
        stop_col_candidates = [c for c in [comment_col, retake_col, *(test_cols or [])] if c]
        criteria_end = min(stop_col_candidates) - 1 if stop_col_candidates else max_col

        for col in range(3, criteria_end + 1):
            v = ws.cell(row=row, column=col).value
            if _is_empty(v):
                issues.append(
                    ValidationIssue(
                        code="EMPTY_CRITERION",
                        severity="critical",
                        sheet=sheet_name,
                        row=row,
                        student=student_name,
                        field=f"col_{col}",
                        message="Не заполнен критерий оценивания",
                    )
                )
            else:
                sv = str(v).strip()
                if sv not in ALLOWED_DESCRIPTOR_VALUES:
                    issues.append(
                        ValidationIssue(
                            code="INVALID_CRITERION_VALUE",
                            severity="warning",
                            sheet=sheet_name,
                            row=row,
                            student=student_name,
                            field=f"col_{col}",
                            message=f"Недопустимое значение критерия: '{sv}'",
                        )
                    )

        # 2) Проверка тестовых баллов
        low_score_found = False
        for col in test_cols:
            raw = ws.cell(row=row, column=col).value
            if _is_empty(raw):
                continue
            try:
                score = float(raw)
                if score < TEST_SCORE_MIN or score > TEST_SCORE_MAX:
                    issues.append(
                        ValidationIssue(
                            code="TEST_SCORE_OUT_OF_RANGE",
                            severity="warning",
                            sheet=sheet_name,
                            row=row,
                            student=student_name,
                            field=f"col_{col}",
                            message=f"Баллы вне диапазона {TEST_SCORE_MIN}-{TEST_SCORE_MAX}: {score}",
                        )
                    )
                if score < LOW_SCORE_THRESHOLD:
                    low_score_found = True
            except Exception:
                issues.append(
                    ValidationIssue(
                        code="TEST_SCORE_NOT_NUMERIC",
                        severity="warning",
                        sheet=sheet_name,
                        row=row,
                        student=student_name,
                        field=f"col_{col}",
                        message=f"Тестовый балл не число: {raw}",
                    )
                )

        # 3) Обязательность комментария/пересдачи при низком балле
        if low_score_found:
            if COMMENT_REQUIRED_IF_LOW_SCORE and comment_col:
                c = ws.cell(row=row, column=comment_col).value
                if _is_empty(c):
                    issues.append(
                        ValidationIssue(
                            code="COMMENT_REQUIRED",
                            severity="critical",
                            sheet=sheet_name,
                            row=row,
                            student=student_name,
                            field=f"col_{comment_col}",
                            message="Нужен комментарий при низком тестовом балле",
                        )
                    )
            if RETAKE_REQUIRED_IF_LOW_SCORE and retake_col:
                r = ws.cell(row=row, column=retake_col).value
                if _is_empty(r):
                    issues.append(
                        ValidationIssue(
                            code="RETAKE_REQUIRED",
                            severity="critical",
                            sheet=sheet_name,
                            row=row,
                            student=student_name,
                            field=f"col_{retake_col}",
                            message="Нужно указать пересдачу при низком тестовом балле",
                        )
                    )

        row += 1

    return issues