import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from notifications.models import TeacherContact


class Command(BaseCommand):
    help = "Generate Telegram deep-link invite for teacher registration"

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, type=str, help="Teacher full name")
        parser.add_argument(
            "--bot-username",
            required=False,
            type=str,
            help="Telegram bot username without @ (fallback: TELEGRAM_BOT_USERNAME env)",
        )

    def handle(self, *args, **options):
        name = options["name"].strip()
        bot_username = (options.get("bot_username") or getattr(settings, "TELEGRAM_BOT_USERNAME", "")).strip()

        if not name:
            raise CommandError("--name is required")
        if not bot_username:
            raise CommandError("Provide --bot-username or TELEGRAM_BOT_USERNAME")

        token = secrets.token_urlsafe(18)
        contact, _ = TeacherContact.objects.get_or_create(name=name)
        contact.registration_token = token
        contact.is_active = False
        contact.save(update_fields=["registration_token", "is_active"])

        link = f"https://t.me/{bot_username}?start=register_{token}"
        self.stdout.write(self.style.SUCCESS(f"Invite for {contact.name}: {link}"))
