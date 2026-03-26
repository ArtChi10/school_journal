import json

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import TeacherContact
from .services import TelegramSendError, send_telegram


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

    if not chat_id or not text.startswith("/start"):
        return JsonResponse({"ok": True, "status": "ignored"})

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
    contact.registration_token = None
    contact.save(update_fields=["chat_id", "is_active", "registration_token"])

    try:
        send_telegram(contact.chat_id, f"Регистрация успешна. Контакт привязан: {contact.name}.")
    except TelegramSendError:
        # Even if confirmation failed, binding is successful
        pass

    return JsonResponse({"ok": True, "status": "registered", "teacher": contact.name})