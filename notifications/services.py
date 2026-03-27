import json
import logging
import time
from uuid import UUID
from urllib import error, parse, request

from django.conf import settings
from jobs.models import JobLog, JobRun
from jobs.services import log_step

logger = logging.getLogger(__name__)


class TelegramSendError(Exception):
    pass


def _log_job_attempt(
    job_run_id: str | UUID | None,
    *,
    level: str,
    message: str,
    chat_id: str,
    attempt: int,
    status: str,
    error_message: str = "",
) -> None:
    if not job_run_id:
        return

    job_run = JobRun.objects.filter(id=job_run_id).first()
    if not job_run:
        logger.warning("JobRun not found for telegram logging", extra={"job_run_id": str(job_run_id)})
        return

    log_step(
        job_run=job_run,
        level=level,
        message=message,
        context={
            "job_run_id": str(job_run_id),
            "chat_id": str(chat_id),
            "attempt": attempt,
            "status": status,
            "error_message": error_message,
        },
    )


def send_telegram(
    chat_id: str,
    text: str,
    retries: int = 1,
    timeout: int = 10,
    job_run_id: str | UUID | None = None,
) -> dict:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise TelegramSendError("TELEGRAM_BOT_TOKEN is not configured")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": str(chat_id), "text": text}
    data = parse.urlencode(payload).encode("utf-8")
    # Requirement: retry should happen at least once after a failure.
    retries = max(1, retries)
    attempts = retries + 1
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            req = request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
            parsed = json.loads(body)
            if not parsed.get("ok"):
                raise TelegramSendError(parsed.get("description", "Unknown Telegram API error"))
            _log_job_attempt(
                job_run_id,
                level=JobLog.Level.INFO,
                message="Telegram message sent successfully",
                chat_id=str(chat_id),
                attempt=attempt,
                status="success",
            )
            return parsed
        except (error.URLError, error.HTTPError, TimeoutError, TelegramSendError, json.JSONDecodeError) as exc:
            last_error = exc
            error_message = str(exc)

            _log_job_attempt(
                job_run_id,
                level=JobLog.Level.ERROR,
                message="Telegram send attempt failed",
                chat_id=str(chat_id),
                attempt=attempt,
                status="error",
                error_message=error_message,
            )

            logger.warning(
                "Telegram send failed",
                extra={
                    "job_run_id": str(job_run_id) if job_run_id else None,
                    "chat_id": str(chat_id),
                    "attempt": attempt,
                    "status": "error",
                    "error_message": error_message,
                },
            )
            if attempt < attempts:
                time.sleep(1)

    raise TelegramSendError(f"Failed to send Telegram message after {attempts} attempts: {last_error}")