import json
import re

from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from jobs.models import JobLog, JobRun
from jobs.services import log_step

from .models import TeacherConfirmation, TeacherContact
from .services import TelegramSendError, send_telegram


CONFIRMATION_REGEX = re.compile(
    r"^\s*(?P<keyword>исправил(?:а)?|готово|done|fixed)"
    r"(?:[\s#:]+(?P<job_id>[0-9a-fA-F-]{36}))?\s*[!.]*\s*$",
    re.IGNORECASE,
)

def _find_last_reminder_job(contact: TeacherContact) -> JobRun | None:
    latest_log = (
        JobLog.objects.filter(
            message__startswith="Reminder sent to ",
            context_json__teacher=contact.name,
        )
        .select_related("job_run")
        .order_by("-ts")
        .first()
    )
    if latest_log:
        return latest_log.job_run

    latest_chat_log = (
        JobLog.objects.filter(
            message__startswith="Reminder sent to ",
            context_json__chat_id=str(contact.chat_id),
        )
        .select_related("job_run")
        .order_by("-ts")
        .first()
    )
    return latest_chat_log.job_run if latest_chat_log else None


def _extract_confirmation_job(explicit_job_id: str | None, contact: TeacherContact) -> tuple[JobRun | None, str | None]:
    if explicit_job_id:
        job_run = JobRun.objects.filter(id=explicit_job_id).first()
        return job_run, explicit_job_id

    return _find_last_reminder_job(contact), None


def _handle_teacher_confirmation(contact: TeacherContact, text: str) -> str:
    matched = CONFIRMATION_REGEX.match(text)
    if not matched:
        maybe_job = _find_last_reminder_job(contact)
        if maybe_job:
            log_step(
                job_run=maybe_job,
                level=JobLog.Level.INFO,
                message="Teacher message ignored",
                context={
                    "teacher": contact.name,
                    "chat_id": str(contact.chat_id),
                    "message_text": text,
                    "reason": "not_confirmation_keyword",
                },
            )
        return "ignored"

    job_run, explicit_job_id = _extract_confirmation_job(matched.group("job_id"), contact)
    if not job_run:
        return "ignored"

    now = timezone.now()
    confirmation, created = TeacherConfirmation.objects.get_or_create(
        job_run=job_run,
        chat_id=str(contact.chat_id),
        defaults={
            "teacher_name": contact.name,
            "status": TeacherConfirmation.Status.CONFIRMED,
            "message_text": text,
            "confirmed_at": now,
        },
    )

    if not created:
        confirmation.teacher_name = contact.name
        confirmation.message_text = text
        confirmation.confirmed_at = now
        confirmation.status = TeacherConfirmation.Status.CONFIRMED
        confirmation.save(update_fields=["teacher_name", "message_text", "confirmed_at", "status"])

    log_step(
        job_run=job_run,
        level=JobLog.Level.INFO,
        message="Teacher confirmation received",
        context={
            "teacher": contact.name,
            "chat_id": str(contact.chat_id),
            "status": TeacherConfirmation.Status.CONFIRMED,
            "is_repeat": not created,
            "message_text": text,
            "explicit_job_id": explicit_job_id or "",
        },
    )
    return "repeat" if not created else "confirmed"

@csrf_exempt
def telegram_webhook(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "invalid json"}, status=400)

    message = payload.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if not chat_id:
        return JsonResponse({"ok": True, "status": "ignored"})

    if text.startswith("/start"):
        # Supported format from deep-link: /start register_<token>
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].startswith("register_"):
            return JsonResponse({"ok": True, "status": "ignored"})
        token = parts[1].replace("register_", "", 1).strip()
        if not token:
            return JsonResponse({"ok": True, "status": "ignored"})

        contact = TeacherContact.objects.filter(registration_token=token).first()
        if not contact:
            try:
                send_telegram(str(chat_id), "Ссылка регистрации недействительна. Обратитесь к администратору.")
            except TelegramSendError:
                pass
            return JsonResponse({"ok": True, "status": "token_not_found"})

        contact.chat_id = str(chat_id)
        contact.is_active = True
        contact.last_seen_at = timezone.now()
        contact.registration_token = None
        contact.save(update_fields=["chat_id", "is_active", "last_seen_at", "registration_token"])

        try:
            send_telegram(contact.chat_id, f"Регистрация успешна. Контакт привязан: {contact.name}.")
        except TelegramSendError:
            # Even if confirmation failed, binding is successful
            pass
        return JsonResponse({"ok": True, "status": "registered", "teacher": contact.name})

    contact = TeacherContact.objects.filter(chat_id=str(chat_id)).first()
    if not contact:
        return JsonResponse({"ok": True, "status": "ignored"})

    contact.last_seen_at = timezone.now()
    contact.save(update_fields=["last_seen_at"])
    status = _handle_teacher_confirmation(contact, text)
    return JsonResponse({"ok": True, "status": status})

