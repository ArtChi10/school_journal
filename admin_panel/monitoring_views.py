import os

from django.conf import settings
from django.db import connections
from django.db.utils import DatabaseError
from django.http import JsonResponse


def healthz(_request):
    return JsonResponse({"status": "ok"})


def readyz(_request):
    checks: dict[str, str] = {}
    http_status = 200

    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["db"] = "ok"
    except DatabaseError:
        checks["db"] = "error"
        http_status = 503

    required_env_vars = [
        key.strip()
        for key in (os.getenv("CRITICAL_ENV_VARS", "DJANGO_SECRET_KEY").split(","))
        if key.strip()
    ]
    missing: list[str] = []
    for key in required_env_vars:
        env_value = (os.getenv(key) or "").strip()
        settings_value = str(getattr(settings, key, "") or "").strip()
        if not env_value and not settings_value:
            missing.append(key)
    if missing:
        checks["env"] = f"missing:{','.join(missing)}"
        http_status = 503
    else:
        checks["env"] = "ok"

    payload = {
        "status": "ok" if http_status == 200 else "degraded",
        "checks": checks,
    }
    return JsonResponse(payload, status=http_status)