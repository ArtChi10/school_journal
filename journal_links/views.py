from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from admin_panel.authz import permission_required_403
from admin_panel.google_oauth import (
    GOOGLE_OAUTH_CODE_VERIFIER_SESSION_KEY,
    GOOGLE_OAUTH_NEXT_SESSION_KEY,
    GOOGLE_OAUTH_STATE_SESSION_KEY,
    GoogleOAuthConfigError,
    build_google_authorization_url,
    complete_google_oauth,
    get_google_oauth_status,
)
from validation.job_runner import run_check_missing_data_job, run_validation_job

from .forms import ClassSheetLinkForm
from .models import ClassSheetLink


def _safe_next_url(request, raw_url: str | None = None) -> str:
    fallback = reverse("journal_links:list_links")
    candidate = raw_url or request.POST.get("next") or request.GET.get("next") or fallback
    if url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return candidate
    return fallback


def _clear_google_oauth_session(request) -> None:
    request.session.pop(GOOGLE_OAUTH_STATE_SESSION_KEY, None)
    request.session.pop(GOOGLE_OAUTH_NEXT_SESSION_KEY, None)
    request.session.pop(GOOGLE_OAUTH_CODE_VERIFIER_SESSION_KEY, None)


@login_required
@permission_required_403("journal_links.view_classsheetlink", message="Доступ запрещён: нет прав на просмотр ссылок классов.")
def list_links(request):
    links = ClassSheetLink.objects.all().order_by("-is_active", "class_code", "id")
    return render(request, "journal_links/list.html", {"links": links, "google_oauth_status": get_google_oauth_status()})

@login_required
@permission_required_403("journal_links.add_classsheetlink", message="Доступ запрещён: нельзя создавать ссылки классов.")
def create_link(request):
    if request.method == "POST":
        form = ClassSheetLinkForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("journal_links:list_links")
    else:
        form = ClassSheetLinkForm()

    return render(
        request,
        "journal_links/form.html",
        {"form": form, "title": "Классы и таблицы: создать ссылку", "submit_label": "Сохранить"},
    )

@login_required
@permission_required_403("journal_links.change_classsheetlink", message="Доступ запрещён: нельзя изменять ссылки классов.")
def edit_link(request, pk):
    link = get_object_or_404(ClassSheetLink, pk=pk)

    if request.method == "POST":
        form = ClassSheetLinkForm(request.POST, instance=link)
        if form.is_valid():
            form.save()
            return redirect("journal_links:list_links")
    else:
        form = ClassSheetLinkForm(instance=link)

    return render(
        request,
        "journal_links/form.html",
        {"form": form, "title": "Классы и таблицы: редактировать ссылку", "submit_label": "Сохранить"},
    )


@require_POST
@login_required
@permission_required_403("journal_links.change_classsheetlink", message="Доступ запрещён: нельзя изменять ссылки классов.")
def disable_link(request, pk):
    link = get_object_or_404(ClassSheetLink, pk=pk)
    link.is_active = False
    link.save(update_fields=["is_active", "updated_at"])
    return redirect("journal_links:list_links")


@require_POST
@login_required
@permission_required_403("jobs.run_validation", message="Доступ запрещён: нельзя запускать валидацию.")
def run_link_validation(request, pk):
    link = get_object_or_404(ClassSheetLink, pk=pk)
    job_run = run_validation_job(link_id=link.id, initiated_by=request.user if request.user.is_authenticated else None)
    return redirect("job_run_detail", run_id=job_run.id)


@require_POST
@login_required
@permission_required_403("jobs.run_check_missing_data", message="Доступ запрещён: нельзя запускать проверку незаполненности.")
def run_missing_data_check(request):
    job_run = run_check_missing_data_job(
        all_active=True,
        initiated_by=request.user if request.user.is_authenticated else None,
    )
    return redirect("job_run_detail", run_id=job_run.id)


@require_POST
@login_required
@permission_required_403(
    "journal_links.change_classsheetlink",
    message="Доступ запрещён: нельзя подключать Google OAuth для таблиц.",
)
def start_google_oauth(request):
    next_url = _safe_next_url(request)
    try:
        authorization_url, state, code_verifier = build_google_authorization_url(request)
    except GoogleOAuthConfigError as exc:
        messages.error(request, f"Google OAuth не настроен: {exc}")
        return redirect(next_url)

    request.session[GOOGLE_OAUTH_STATE_SESSION_KEY] = state
    request.session[GOOGLE_OAUTH_CODE_VERIFIER_SESSION_KEY] = code_verifier
    request.session[GOOGLE_OAUTH_NEXT_SESSION_KEY] = next_url
    return redirect(authorization_url)


@login_required
@permission_required_403(
    "journal_links.change_classsheetlink",
    message="Доступ запрещён: нельзя подключать Google OAuth для таблиц.",
)
def google_oauth_callback(request):
    next_url = _safe_next_url(request, request.session.get(GOOGLE_OAUTH_NEXT_SESSION_KEY))
    expected_state = request.session.get(GOOGLE_OAUTH_STATE_SESSION_KEY)
    code_verifier = request.session.get(GOOGLE_OAUTH_CODE_VERIFIER_SESSION_KEY)

    if request.GET.get("error"):
        messages.error(request, f"Google OAuth отклонён: {request.GET['error']}")
        _clear_google_oauth_session(request)
        return redirect(next_url)

    if not expected_state or request.GET.get("state") != expected_state:
        messages.error(request, "Google OAuth не завершён: state не совпал.")
        _clear_google_oauth_session(request)
        return redirect(next_url)

    try:
        token_path = complete_google_oauth(request, state=expected_state, code_verifier=code_verifier)
    except GoogleOAuthConfigError as exc:
        messages.error(request, f"Google OAuth не настроен: {exc}")
        return redirect(next_url)
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f"Google OAuth не сохранил токен: {exc}")
        return redirect(next_url)
    finally:
        _clear_google_oauth_session(request)

    messages.success(request, f"Google OAuth подключён. Токен сохранён: {token_path}")
    return redirect(next_url)
