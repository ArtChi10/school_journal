import csv
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
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
from jobs.models import JobRun
from notifications.descriptor_fill_reminders import send_descriptor_fill_reminders
from validation.descriptor_criteria_fill import (
    JOB_TYPE as DESCRIPTOR_CRITERIA_FILL_JOB_TYPE,
    enqueue_descriptor_criteria_fill_check_job,
)
from validation.job_runner import run_check_missing_data_job, run_validation_job

from .descriptor_fill_report import (
    CSV_HEADERS,
    PROBLEM_TYPE_CHOICES,
    RECENT_RUN_LIMIT,
    REPORT_JOB_TYPE,
    REPORT_STATUSES,
    REPORT_STATUS_VALUES,
    STATUS_CHOICES,
    build_problem_export_rows,
    build_summary,
    build_teacher_groups,
    criteria_problem_rows,
    descriptor_problem_rows,
    filter_options,
    filter_rows,
    grades_problem_rows,
    rows_from_job_run,
    run_choice_label,
)
from .forms import ClassSheetLinkForm, DescriptorCriteriaCheckScheduleForm, DescriptorCriteriaReportTargetForm
from .models import ClassSheetLink, DescriptorCriteriaCheckSchedule, DescriptorCriteriaReportTarget


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


def _non_empty(value: str | None) -> str:
    return (value or "").strip()


def _format_missing_contacts_message(summary: dict) -> str:
    names = summary.get("missing_contacts", [])
    if not isinstance(names, list):
        return ""
    normalized_names = [str(name).strip() for name in names if str(name).strip()]
    if not normalized_names:
        return ""

    visible_names = normalized_names[:20]
    message = "Не найдены в списке Telegram-бота: " + ", ".join(visible_names)
    hidden_count = len(normalized_names) - len(visible_names)
    if hidden_count > 0:
        message = f"{message} и еще {hidden_count}"
    return f"{message}."


def _latest_descriptor_criteria_run() -> JobRun | None:
    return (
        JobRun.objects.filter(job_type=DESCRIPTOR_CRITERIA_FILL_JOB_TYPE)
        .order_by("-started_at", "-id")
        .first()
    )


def _descriptor_criteria_rows(job_run: JobRun | None) -> list[dict]:
    if job_run is None or not isinstance(job_run.result_json, dict):
        return []
    rows = job_run.result_json.get("rows", [])
    return [row for row in rows if isinstance(row, dict)]


def _filter_descriptor_criteria_rows(rows: list[dict], request) -> list[dict]:
    class_code = _non_empty(request.GET.get("class_code"))
    teacher = _non_empty(request.GET.get("teacher"))
    status = _non_empty(request.GET.get("status"))

    filtered = rows
    if class_code:
        filtered = [row for row in filtered if str(row.get("class_code", "")) == class_code]
    if teacher:
        teacher_lower = teacher.lower()
        filtered = [row for row in filtered if teacher_lower in str(row.get("teacher_name", "")).lower()]
    if status:
        filtered = [row for row in filtered if str(row.get("overall_status", "")) == status]
    return filtered


def _descriptor_criteria_filter_options(rows: list[dict]) -> dict[str, list[str]]:
    return {
        "classes": sorted({str(row.get("class_code") or "") for row in rows if row.get("class_code")}),
        "teachers": sorted({str(row.get("teacher_name") or "") for row in rows if row.get("teacher_name")}),
    }


def _descriptor_fill_report_data(request) -> dict:
    status = _non_empty(request.GET.get("status"))
    if status not in REPORT_STATUS_VALUES:
        status = ""
    problem_type = _non_empty(request.GET.get("problem_type"))
    if problem_type not in {"descriptor", "criteria", "grades"}:
        problem_type = ""

    report_runs = JobRun.objects.filter(
        job_type=REPORT_JOB_TYPE,
        status__in=REPORT_STATUSES,
    ).order_by("-started_at", "-id")
    filtered_runs = report_runs.filter(status=status) if status else report_runs
    run_choices = [
        {"id": str(job_run.id), "label": run_choice_label(job_run)}
        for job_run in filtered_runs[:RECENT_RUN_LIMIT]
    ]

    selected_run_id = _non_empty(request.GET.get("run_id"))
    if selected_run_id:
        job_run = get_object_or_404(report_runs, id=selected_run_id)
    else:
        job_run = filtered_runs.first()

    rows = rows_from_job_run(job_run)
    class_code = _non_empty(request.GET.get("class_code"))
    teacher = _non_empty(request.GET.get("teacher"))
    filtered_rows = filter_rows(rows, class_code=class_code, teacher=teacher)
    descriptor_rows = descriptor_problem_rows(filtered_rows, problem_type=problem_type)
    criteria_rows = criteria_problem_rows(filtered_rows, problem_type=problem_type)
    grades_rows = grades_problem_rows(filtered_rows, problem_type=problem_type)
    problem_total = len(descriptor_rows) + len(criteria_rows) + len(grades_rows)

    return {
        "job_run": job_run,
        "run_choices": run_choices,
        "summary": build_summary(job_run, filtered_rows),
        "descriptor_rows": descriptor_rows,
        "criteria_rows": criteria_rows,
        "grades_rows": grades_rows,
        "teacher_groups": build_teacher_groups(filtered_rows, problem_type=problem_type),
        "filter_options": filter_options(rows),
        "problem_total": problem_total,
        "status_choices": STATUS_CHOICES,
        "problem_type_choices": PROBLEM_TYPE_CHOICES,
        "filters": {
            "run_id": str(job_run.id) if job_run else selected_run_id,
            "class_code": class_code,
            "teacher": teacher,
            "problem_type": problem_type,
            "status": status,
        },
        "querystring": request.GET.urlencode(),
    }


@login_required
@permission_required_403("journal_links.view_classsheetlink", message="Доступ запрещён: нет прав на просмотр ссылок классов.")
def list_links(request):
    links = ClassSheetLink.objects.all().order_by("id")
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


@login_required
@permission_required_403(
    "jobs.run_check_missing_data",
    message="Доступ запрещён: нельзя запускать проверку дескрипторов и критериев.",
)
def descriptor_criteria_fill_check(request):
    active_links = list(ClassSheetLink.objects.filter(is_active=True).order_by("class_code", "id"))
    class_options = sorted({link.class_code for link in active_links})
    schedule = DescriptorCriteriaCheckSchedule.load()

    if request.method == "POST":
        action = _non_empty(request.POST.get("action")) or "run_check"
        if action == "save_schedule":
            was_enabled = schedule.is_enabled
            previous_interval_minutes = schedule.interval_minutes
            schedule_form = DescriptorCriteriaCheckScheduleForm(request.POST, instance=schedule)
            if schedule_form.is_valid():
                schedule = schedule_form.save(commit=False)
                schedule.updated_by = request.user if request.user.is_authenticated else None
                interval_changed = schedule.interval_minutes != previous_interval_minutes
                if schedule.is_enabled and (not was_enabled or schedule.next_run_at is None):
                    schedule.next_run_at = timezone.now()
                elif schedule.is_enabled and interval_changed:
                    schedule.next_run_at = timezone.now() + timedelta(minutes=schedule.interval_minutes)
                schedule.save()
                messages.success(request, "Настройки автопроверки сохранены.")
                return redirect("journal_links:descriptor_criteria_fill_check")
        else:
            if action == "run_now":
                class_code = None
            else:
                class_code = _non_empty(request.POST.get("class_code")) or None
            job_run = enqueue_descriptor_criteria_fill_check_job(
                class_code=class_code,
                all_active=class_code is None,
                initiated_by=request.user if request.user.is_authenticated else None,
                trigger="manual",
            )
            messages.success(request, "Проверка дескрипторов, критериев и оценок запущена.")
            return redirect(f"{reverse('journal_links:descriptor_criteria_fill_check')}?run_id={job_run.id}")
    else:
        schedule_form = DescriptorCriteriaCheckScheduleForm(instance=schedule)

    requested_run_id = _non_empty(request.GET.get("run_id"))
    job_run = None
    if requested_run_id:
        job_run = get_object_or_404(JobRun, id=requested_run_id, job_type=DESCRIPTOR_CRITERIA_FILL_JOB_TYPE)
    else:
        job_run = _latest_descriptor_criteria_run()

    rows = _descriptor_criteria_rows(job_run)
    filtered_rows = _filter_descriptor_criteria_rows(rows, request)
    summary = {}
    if job_run and isinstance(job_run.result_json, dict):
        possible_summary = job_run.result_json.get("summary", {})
        if isinstance(possible_summary, dict):
            summary = possible_summary

    return render(
        request,
        "journal_links/descriptor_criteria_fill_check.html",
        {
            "active_links": active_links,
            "class_options": class_options,
            "filter_options": _descriptor_criteria_filter_options(rows),
            "filters": {
                "class_code": request.GET.get("class_code", ""),
                "teacher": request.GET.get("teacher", ""),
                "status": request.GET.get("status", ""),
            },
            "job_run": job_run,
            "summary": summary,
            "rows": filtered_rows,
            "schedule": schedule,
            "schedule_form": schedule_form,
        },
    )


@login_required
@permission_required_403("jobs.view_jobrun", message="Доступ запрещён: нет прав на просмотр отчета заполненности.")
def descriptor_criteria_fill_report(request):
    return render(
        request,
        "journal_links/descriptor_criteria_fill_report.html",
        _descriptor_fill_report_data(request),
    )


@login_required
@permission_required_403("jobs.view_jobrun", message="Доступ запрещён: нет прав на экспорт отчета заполненности.")
def descriptor_criteria_fill_report_csv(request):
    report_data = _descriptor_fill_report_data(request)
    job_run = report_data["job_run"]
    rows = filter_rows(
        rows_from_job_run(job_run),
        class_code=report_data["filters"]["class_code"],
        teacher=report_data["filters"]["teacher"],
    )
    export_rows = build_problem_export_rows(rows, problem_type=report_data["filters"]["problem_type"])

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    filename = f"descriptor-fill-report-{job_run.id}.csv" if job_run else "descriptor-fill-report.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    writer = csv.DictWriter(response, fieldnames=CSV_HEADERS)
    writer.writerow({header: header for header in CSV_HEADERS})
    writer.writerows(export_rows)
    return response


@require_POST
@login_required
@permission_required_403("jobs.send_reminders", message="Доступ запрещён: нельзя отправлять напоминания преподавателям.")
def send_descriptor_criteria_fill_reminders(request, run_id):
    source_job_run = get_object_or_404(
        JobRun,
        id=run_id,
        job_type=REPORT_JOB_TYPE,
        status__in=REPORT_STATUSES,
    )
    reminder_job = send_descriptor_fill_reminders(
        source_job_run,
        initiated_by=request.user if request.user.is_authenticated else None,
    )
    summary = reminder_job.result_json.get("summary", {}) if isinstance(reminder_job.result_json, dict) else {}
    messages.success(
        request,
        (
            "Напоминания преподавателям обработаны: "
            f"учителей={summary.get('teachers_total', 0)}, "
            f"отправлено={summary.get('sent', 0)}, "
            f"без контакта={summary.get('skipped_no_contact', 0)}, "
            f"дубли={summary.get('skipped_duplicate', 0)}, "
            f"ошибки={summary.get('failed', 0)}."
        ),
    )
    missing_contacts_message = _format_missing_contacts_message(summary)
    if missing_contacts_message:
        messages.warning(request, missing_contacts_message)
    return redirect("job_run_detail", run_id=reminder_job.id)


@login_required
@permission_required_403(
    "journal_links.change_classsheetlink",
    message="Доступ запрещён: нельзя изменять Google-отчет дескрипторов и критериев.",
)
def descriptor_criteria_report_target(request):
    target = DescriptorCriteriaReportTarget.objects.order_by("-is_active", "-updated_at", "-id").first()

    if request.method == "POST":
        form = DescriptorCriteriaReportTargetForm(request.POST, instance=target)
        if form.is_valid():
            target = form.save()
            messages.success(request, "Google-отчет дескрипторов и критериев сохранен.")
            return redirect("journal_links:descriptor_criteria_report_target")
    else:
        form = DescriptorCriteriaReportTargetForm(instance=target)

    return render(
        request,
        "journal_links/descriptor_criteria_report_target.html",
        {
            "form": form,
            "target": target,
        },
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
