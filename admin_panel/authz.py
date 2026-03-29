from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden


def permission_required_403(perm: str, *, message: str | None = None) -> Callable:
    """Check permission and return 403 with a human-readable message when denied."""

    deny_message = message or "Доступ запрещён: недостаточно прав для выполнения действия."

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if request.user.has_perm(perm):
                return view_func(request, *args, **kwargs)

            messages.error(request, deny_message)
            return HttpResponseForbidden(deny_message)

        return _wrapped

    return decorator