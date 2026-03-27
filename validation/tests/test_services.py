import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase
from openpyxl import Workbook

from validation.services import WorkbookReadError, validate_workbook


ALLOWED_DESCRIPTOR = "Выполняет самостоятельно | Independent"


def _build_valid_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Grade5A"

    ws.cell(row=5, column=1, value="Имя")
    ws.cell(row=5, column=2, value="Фамилия")
    ws.cell(row=5, column=3, value="Критерий 1")
    ws.cell(row=5, column=4, value="Критерий 2")
    ws.cell(row=5, column=5, value="Тест 1")
    ws.cell(row=5, column=6, value="Комментарий")
    ws.cell(row=5, column=7, value="Пересдача")

    ws.cell(row=7, column=1, value="Иван")
    ws.cell(row=7, column=2, value="Иванов")
    ws.cell(row=7, column=3, value=ALLOWED_DESCRIPTOR)
    ws.cell(row=7, column=4, value=ALLOWED_DESCRIPTOR)
    ws.cell(row=7, column=5, value=75)

    wb.save(path)


def _build_problem_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Grade5B"

    ws.cell(row=5, column=1, value="Имя")
    ws.cell(row=5, column=2, value="Фамилия")
    ws.cell(row=5, column=3, value="Критерий 1")
    ws.cell(row=5, column=4, value="Тест 1")
    ws.cell(row=5, column=5, value="Тест 2")
    ws.cell(row=5, column=6, value="Комментарий")
    ws.cell(row=5, column=7, value="Пересдача")

    ws.cell(row=7, column=1, value="Петр")
    ws.cell(row=7, column=2, value="Петров")
    ws.cell(row=7, column=3, value="invalid descriptor")
    ws.cell(row=7, column=4, value="abc")
    ws.cell(row=7, column=5, value=20)

    wb.save(path)


class ValidateWorkbookTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmpdir = tempfile.TemporaryDirectory()
        tmp_path = Path(cls._tmpdir.name)
        cls.valid_file = tmp_path / "valid_workbook.xlsx"
        cls.problem_file = tmp_path / "problem_workbook.xlsx"

        _build_valid_workbook(cls.valid_file)
        _build_problem_workbook(cls.problem_file)

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()
        super().tearDownClass()

    def test_valid_workbook_returns_unified_json_shape(self):
        result = validate_workbook(str(self.valid_file))

        self.assertEqual(set(result.keys()), {"summary", "issues"})
        self.assertEqual(
            set(result["summary"].keys()),
            {"total", "critical", "warning", "info"},
        )
        self.assertEqual(result["summary"], {"total": 0, "critical": 0, "warning": 0, "info": 0})
        self.assertEqual(result["issues"], [])

        # ручная проверка JSON-формата (сериализация без ошибок)
        payload = json.dumps(result, ensure_ascii=False)
        self.assertIn('"summary"', payload)
        self.assertIn('"issues"', payload)

    def test_problem_workbook_uses_unified_issue_schema(self):
        result = validate_workbook(str(self.problem_file))

        self.assertGreater(result["summary"]["total"], 0)
        self.assertEqual(result["summary"]["critical"], 2)
        self.assertEqual(result["summary"]["warning"], 2)
        self.assertEqual(result["summary"]["info"], 0)

        self.assertEqual(len(result["issues"]), result["summary"]["total"])

        required_issue_keys = {
            "code",
            "severity",
            "sheet",
            "row",
            "student",
            "field",
            "message",
        }
        for issue in result["issues"]:
            self.assertEqual(set(issue.keys()), required_issue_keys)

    def test_read_errors_raise_predictable_exception(self):
        with self.assertRaises(WorkbookReadError):
            validate_workbook("not_existing_workbook.xlsx")

    def test_invalid_xlsx_content_raises_predictable_exception(self):
        broken_file = Path(self._tmpdir.name) / "broken.xlsx"
        broken_file.write_text("not an xlsx file", encoding="utf-8")

        with self.assertRaises(WorkbookReadError):
            validate_workbook(str(broken_file))