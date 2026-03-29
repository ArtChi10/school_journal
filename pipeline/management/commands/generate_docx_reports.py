from django.core.management.base import BaseCommand, CommandError

from pipeline.docx_job_runner import run_generate_docx_job


class Command(BaseCommand):
    help = "Generate per-class DOCX reports from downloaded XLSX files"

    def add_arguments(self, parser):
        parser.add_argument(
            "--xlsx",
            dest="xlsx_files",
            action="append",
            default=[],
            help="Path to downloaded class workbook (.xlsx). Can be provided multiple times.",
        )
        parser.add_argument(
            "--output-root",
            type=str,
            default="output",
            help="Root output directory where class subfolders will be created",
        )
        parser.add_argument(
            "--upload-review",
            action="store_true",
            help="Upload generated DOCX files to Google Drive review folder",
        )

    def handle(self, *args, **options):
        xlsx_files = options.get("xlsx_files") or []
        output_root = options.get("output_root") or "output"

        if not xlsx_files:
            raise CommandError("Specify at least one --xlsx <path> argument")

        job_run = run_generate_docx_job(
            xlsx_files=xlsx_files,
            output_root=output_root,
            upload_to_review=bool(options.get("upload_review")),
        )
        result = job_run.result_json or {}
        self.stdout.write(
            self.style.SUCCESS(
                "DOCX generation job created: "
                f"id={job_run.id} status={job_run.status} "
                f"docx_total={result.get('docx_total', 0)} "
                f"docx_success={result.get('docx_success', 0)} "
                f"docx_failed={result.get('docx_failed', 0)} "
                f"uploaded_success={result.get('uploaded_success', 0)} "
                f"uploaded_failed={result.get('uploaded_failed', 0)}"
            )
        )