from django.core.management.base import BaseCommand, CommandError

from pipeline.services_pdf import run_convert_docx_to_pdf_step


class Command(BaseCommand):
    help = "Convert DOCX files to PDF and split outputs by class_code"

    def add_arguments(self, parser):
        parser.add_argument(
            "--docx",
            dest="docx_files",
            action="append",
            default=[],
            help="Path to DOCX file. Can be provided multiple times.",
        )

    def handle(self, *args, **options):
        docx_files = options.get("docx_files") or []
        if not docx_files:
            raise CommandError("Specify at least one --docx <path> argument")

        result = run_convert_docx_to_pdf_step(docx_files=docx_files)
        self.stdout.write(
            self.style.SUCCESS(
                "DOCX->PDF conversion completed: "
                f"pdf_total={result.get('pdf_total', 0)} "
                f"pdf_success={result.get('pdf_success', 0)} "
                f"pdf_failed={result.get('pdf_failed', 0)}"
            )
        )