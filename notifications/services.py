import json
import logging
import time
from urllib import error, parse, request

from django.conf import settings

logger = logging.getLogger(__name__)


class TelegramSendError(Exception):
    pass


def send_telegram(chat_id: str, text: str, retries: int = 1, timeout: int = 10) -> dict:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise TelegramSendError("TELEGRAM_BOT_TOKEN is not configured")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": str(chat_id), "text": text}
    data = parse.urlencode(payload).encode("utf-8")

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
            return parsed
        except (error.URLError, error.HTTPError, TimeoutError, TelegramSendError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning("Telegram send failed (attempt %s/%s): %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(1)

    raise TelegramSendError(f"Failed to send Telegram message after {attempts} attempts: {last_error}")