from __future__ import annotations

import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from pipeline.parent_reports_job_runner import run_send_parent_reports_job


class Command(BaseCommand):
    help = "Send prepared PDF reports to parent recipients and store per-recipient statuses"

    def add_arguments(self, parser):
        parser.add_argument("--contacts-json", type=str, required=True, help="Path to JSON array with contacts")
        parser.add_argument("--pdf-root", type=str, default="output/pdf", help="Folder with prepared PDFs")
        parser.add_argument("--contacts-csv", type=str, help="Optional CSV fallback: class_code,student,email")

    def _load_contacts(self, contacts_json: Path, contacts_csv: Path | None) -> list[dict]:
        if contacts_json.exists():
            payload = json.loads(contacts_json.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise CommandError("contacts-json must contain a JSON array")
            return payload

        if contacts_csv and contacts_csv.exists():
            contacts = []
            with contacts_csv.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    contacts.append(
                        {
                            "class_code": (row.get("class_code") or "").strip(),
                            "student": (row.get("student") or "").strip(),
                            "recipients": [{"channel": "email", "value": (row.get("email") or "").strip()}],
                        }
                    )
            return contacts

        raise CommandError("Provide existing --contacts-json (or --contacts-csv fallback)")

    def handle(self, *args, **options):
        contacts_json = Path(options["contacts_json"]).resolve()
        contacts_csv = Path(options["contacts_csv"]).resolve() if options.get("contacts_csv") else None
        pdf_root = Path(options["pdf_root"]).resolve()

        contacts = self._load_contacts(contacts_json=contacts_json, contacts_csv=contacts_csv)
        pdf_files = [{"path": str(path)} for path in pdf_root.rglob("*.pdf")]

        if not pdf_files:
            self.stdout.write(self.style.WARNING(f"No PDF files found in {pdf_root}"))

        job_run = run_send_parent_reports_job(pdf_files=pdf_files, contacts=contacts)

        result = job_run.result_json or {}
        self.stdout.write(
            self.style.SUCCESS(
                "Parent report job finished "
                f"id={job_run.id} status={job_run.status} "
                f"students={result.get('students_total', 0)} "
                f"sent_success={result.get('sent_success', 0)} "
                f"sent_failed={result.get('sent_failed', 0)} "
                f"skipped_no_contact={result.get('skipped_no_contact', 0)} "
                f"skipped_no_pdf={result.get('skipped_no_pdf', 0)}"
            )
        )