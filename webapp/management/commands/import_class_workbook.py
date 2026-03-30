import json

from django.core.management.base import BaseCommand, CommandError

from webapp.parsing import import_class_workbook


class Command(BaseCommand):
    help = "Import class workbook (all sheets) into DATA-101 tables with parse statistics"

    def add_arguments(self, parser):
        parser.add_argument("--workbook-path", type=str, required=True, help="Path to local .xlsx workbook")
        parser.add_argument("--class-code", type=str, required=True, help="Class code, e.g. 4A")
        parser.add_argument("--source-url", type=str, required=True, help="Workbook source URL")
        parser.add_argument("--period", type=str, required=True, help="Period label, e.g. module-1")

    def handle(self, *args, **options):
        workbook_path = options["workbook_path"]
        class_code = options["class_code"]
        source_url = options["source_url"]
        period = options["period"]

        try:
            result = import_class_workbook(
                workbook_path=workbook_path,
                class_code=class_code,
                source_url=source_url,
                period=period,
            )
        except Exception as exc:
            raise CommandError(f"Workbook import failed: {exc}") from exc

        payload = {
            "workbook_id": result.workbook_id,
            "class_code": result.class_code,
            "summary": {
                "sheets_total": result.sheets_total,
                "sheets_imported": result.sheets_imported,
                "tutor_sheets": result.tutor_sheets,
                "sheets_skipped": result.sheets_skipped,
                "criteria_created": result.criteria_created,
                "students_created": result.students_created,
                "assessments_created": result.assessments_created,
            },
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=False))