import csv

from django.core.management.base import BaseCommand, CommandError

from notifications.models import TeacherContact


class Command(BaseCommand):
    help = "Import teacher contacts from CSV with columns: name,chat_id[,is_active]"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str)

    def handle(self, *args, **options):
        csv_path = options["csv_path"]

        created = 0
        updated = 0

        try:
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                required = {"name", "chat_id"}
                if not required.issubset(set(reader.fieldnames or [])):
                    raise CommandError("CSV must contain headers: name, chat_id")

                for row in reader:
                    name = (row.get("name") or "").strip()
                    chat_id = (row.get("chat_id") or "").strip()
                    is_active_raw = (row.get("is_active") or "").strip().lower()

                    if not name or not chat_id:
                        self.stdout.write(self.style.WARNING(f"Skipped row with empty name/chat_id: {row}"))
                        continue

                    is_active = is_active_raw not in {"0", "false", "no", "off"}

                    obj, was_created = TeacherContact.objects.update_or_create(
                        name=name,
                        defaults={"chat_id": chat_id, "is_active": is_active},
                    )

                    if was_created:
                        created += 1
                    else:
                        updated += 1

                    self.stdout.write(f"Upserted: {obj.name} -> {obj.chat_id} (active={obj.is_active})")
        except FileNotFoundError as exc:
            raise CommandError(f"CSV file not found: {csv_path}") from exc

        self.stdout.write(self.style.SUCCESS(f"Done. created={created}, updated={updated}"))