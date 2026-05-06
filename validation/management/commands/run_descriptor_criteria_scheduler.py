import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from validation.descriptor_criteria_scheduler import SCHEDULER_POLL_SECONDS, run_due_descriptor_criteria_schedule

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run descriptor, criteria, and grades scheduler worker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sleep-seconds",
            type=int,
            default=SCHEDULER_POLL_SECONDS,
            help="Seconds to sleep between scheduler ticks.",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run a single scheduler tick and exit.",
        )

    def handle(self, *args, **options):
        sleep_seconds = max(1, int(options["sleep_seconds"]))
        run_once = bool(options["once"])
        self.stdout.write("Descriptor criteria scheduler started")

        while True:
            close_old_connections()
            try:
                run_due_descriptor_criteria_schedule()
            except Exception:  # noqa: BLE001
                logger.exception("Descriptor criteria scheduler tick failed")
            finally:
                close_old_connections()

            if run_once:
                break
            time.sleep(sleep_seconds)
