from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


class LegacyDocxGenerationError(RuntimeError):
    """Raised when legacy DOCX generation cannot be executed."""


class LegacyDocxGenerator:
    """Adapter around the legacy school_journal-main generator scripts."""

    def __init__(self, legacy_root: Path | None = None, template_path: Path | None = None):
        base_dir = Path(__file__).resolve().parent.parent
        self.legacy_root = legacy_root or (base_dir / "school_journal-main")
        default_template_candidates = [
            self.legacy_root / "input" / "first page template.docx",
            self.legacy_root / "input" / "First page template.docx",
            self.legacy_root / "input" / "_First page template.docx",
        ]
        if template_path is not None:
            self.template_path = template_path
        else:
            self.template_path = next((p for p in default_template_candidates if p.exists()), default_template_candidates[0])

        if not self.legacy_root.exists():
            raise LegacyDocxGenerationError(f"Legacy source directory does not exist: {self.legacy_root}")
        if not self.template_path.exists():
            raise LegacyDocxGenerationError(f"Legacy template does not exist: {self.template_path}")

    def _load_module(self, module_name: str, file_name: str):
        module_path = self.legacy_root / file_name
        spec = importlib.util.spec_from_file_location(module_name, str(module_path))
        if spec is None or spec.loader is None:
            raise LegacyDocxGenerationError(f"Cannot load legacy module: {module_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def generate_for_workbook(self, workbook_path: Path, output_dir: Path, temp_dir: Path) -> list[str]:
        """
        Generate per-student DOCX reports for a single workbook using legacy algorithms.

        Returns list of created file paths.
        """
        workbook_path = Path(workbook_path)
        output_dir = Path(output_dir)
        temp_dir = Path(temp_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        legacy_root = str(self.legacy_root)
        if legacy_root not in sys.path:
            sys.path.insert(0, legacy_root)

        try:
            # ensure shared modules are importable under names expected by legacy scripts
            self._load_module("marks_dict", "marks_dict.py")
            helpers = self._load_module("helpers", "helpers.py")
            generate_page = self._load_module("generate_page", "generate_page.py")
            legacy_main = self._load_module("legacy_main", "main.py")

            students = legacy_main.create_students_from_xlsx(str(workbook_path))
            headers = legacy_main.fill_header(
                students,
                str(self.template_path),
                str(temp_dir),
                str(workbook_path),
            )
            subject_tables = generate_page.generate_subject(students, str(temp_dir))

            created_paths: list[str] = []
            for header in headers:
                for table in subject_tables:
                    if header["student"] == table["student"]:
                        helpers.merge_documents(header["filepath"], table["filepath"], header["filepath"])

                helpers.copy_and_rename_file(header["filepath"], str(output_dir), header["filename"])
                created_paths.append(str(output_dir / header["filename"]))

            helpers.cleanup_folder(str(temp_dir))
            return created_paths
        except Exception as exc:  # noqa: BLE001
            raise LegacyDocxGenerationError(str(exc)) from exc