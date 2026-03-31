from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
import csv
import json
from django.views.decorators.http import require_POST
from admin_panel.authz import permission_required_403
from notifications.reminders import run_validation_reminders_job
from validation.job_runner import run_check_missing_data_job

from pipeline.full_pipeline_runner import run_full_pipeline

from .models import JobRun

STATUS_UI_META = {
    JobRun.Status.PENDING: {"css": "queued", "label": "queued"},
    JobRun.Status.RUNNING: {"css": "running", "label": "running"},
    JobRun.Status.SUCCESS: {"css": "success", "label": "success"},
    JobRun.Status.PARTIAL: {"css": "partial", "label": "partial"},
    JobRun.Status.FAILED: {"css": "failed", "label": "failed"},
}

def _parse_non_empty(value: str | None) -> str | None:
    if value is None:
        return None

    trimmed = value.strip()
    return trimmed or None


def _status_meta(status: str | None) -> dict[str, str]:
    return STATUS_UI_META.get(status, {"css": "queued", "label": status or "queued"})


def _build_step_rows(job_run: JobRun, logs, pipeline_steps, errors_payload):
    log_indexes: dict[str, dict[str, dict]] = {}
    for log in logs:
        if not isinstance(log.context_json, dict):
            continue
        step_key = log.context_json.get("step")
        if not step_key:
            continue
        bucket = log_indexes.setdefault(step_key, {})
        if log.message == "step_started":
            bucket["started"] = {"ts": log.ts, "context": log.context_json}
        elif log.message in {"step_success", "step_failed"}:
            bucket["finished"] = {
                "ts": log.ts,
                "context": log.context_json,
                "message": log.message,
                "level": log.level,
            }

    errors_by_step: dict[str, list[dict]] = {}
    for error in errors_payload:
        if isinstance(error, dict) and error.get("step"):
            errors_by_step.setdefault(error["step"], []).append(error)

    step_rows = []
    for index, step in enumerate(pipeline_steps):
        step_key = step.get("key") or f"step-{index + 1}"
        indexed_logs = log_indexes.get(step_key, {})
        started_log = indexed_logs.get("started")
        finished_log = indexed_logs.get("finished")
        status = step.get("status") or "pending"

        reasons = []
        if isinstance(step.get("reason"), str) and step.get("reason"):
            reasons.append(step["reason"])

        if isinstance(finished_log, dict):
            reason = (finished_log.get("context") or {}).get("reason")
            if reason:
                reasons.append(str(reason))

        for payload in errors_by_step.get(step_key, []):
            reason = payload.get("reason")
            if reason:
                reasons.append(str(reason))

        unique_reasons = []
        for value in reasons:
            if value not in unique_reasons:
                unique_reasons.append(value)

        context_details = {
            "step": step,
            "error_entries": errors_by_step.get(step_key, []),
            "start_context": (started_log or {}).get("context", {}),
            "finish_context": (finished_log or {}).get("context", {}),
        }

        step_rows.append(
            {
                "anchor": f"step-{step_key.lower()}",
                "key": step_key,
                "title": step.get("title") or "—",
                "status": status,
                "status_meta": _status_meta(status),
                "started_at": (started_log or {}).get("ts"),
                "finished_at": (finished_log or {}).get("ts"),
                "error_reason": " | ".join(unique_reasons),
                "context_details": context_details,
            }
        )

    return step_rows

def _resolve_problem_step(step_rows):
    for step in step_rows:
        if step["status"] in {JobRun.Status.PARTIAL, JobRun.Status.FAILED, "partial", "failed"}:
            return step
    return None

ISSUES_EXPORT_COLUMNS = [
    "sheet",
    "class_code",
    "subject_name",
    "teacher_name",
    "student",
    "row",
    "field",
    "code",
    "severity",
    "message",
    "issue_group",
    "missing_count",
]

def _extract_issues_payload(job_run: JobRun) -> list[dict]:
    payload = (job_run.result_json or {}).get("issues", [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _apply_issue_filters(issues: list[dict], request) -> list[dict]:
    code = _parse_non_empty(request.GET.get("code"))
    teacher = _parse_non_empty(request.GET.get("teacher"))
    class_code = _parse_non_empty(request.GET.get("class_code"))
    subject = _parse_non_empty(request.GET.get("subject_name"))

    filtered = issues
    if code:
        filtered = [i for i in filtered if str(i.get("code", "")) == code]
    if teacher:
        filtered = [i for i in filtered if teacher.lower() in str(i.get("teacher_name", "")).lower()]
    if class_code:
        filtered = [i for i in filtered if class_code.lower() in str(i.get("class_code", "")).lower()]
    if subject:
        filtered = [i for i in filtered if subject.lower() in str(i.get("subject_name", "")).lower()]
    return filtered

def _normalize_issue_row(issue: dict) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key in ISSUES_EXPORT_COLUMNS:
        value = issue.get(key)
        normalized[key] = "" if value is None else str(value)
    return normalized


@login_required
@permission_required_403("jobs.view_jobrun", message="Доступ запрещён: нет прав на просмотр запусков.")
def list_job_runs(request):
    queryset = JobRun.objects.all().order_by("-started_at")

    status = _parse_non_empty(request.GET.get("status"))
    if status:
        queryset = queryset.filter(status=status)

    job_type = _parse_non_empty(request.GET.get("job_type"))
    if job_type:
        queryset = queryset.filter(job_type=job_type)

    started_from = _parse_non_empty(request.GET.get("started_from"))
    if started_from:
        queryset = queryset.filter(started_at__date__gte=started_from)

    started_to = _parse_non_empty(request.GET.get("started_to"))
    if started_to:
        queryset = queryset.filter(started_at__date__lte=started_to)

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    for run in page_obj:
        run.status_meta = _status_meta(run.status)

    preserved_query = request.GET.copy()
    preserved_query.pop("page", None)

    return render(
        request,
        "jobs/jobrun_list.html",
        {
            "page_obj": page_obj,
            "status_choices": JobRun.Status.choices,
            "job_type_choices": JobRun.objects.values_list("job_type", flat=True).distinct().order_by("job_type"),
            "filters": {
                "status": status or "",
                "job_type": job_type or "",
                "started_from": started_from or "",
                "started_to": started_to or "",
            },
            "querystring": preserved_query.urlencode(),
        },
    )

@login_required
@permission_required_403("jobs.view_jobrun", message="Доступ запрещён: нет прав на просмотр запуска.")
def job_run_detail(request, run_id):
    job_run = get_object_or_404(JobRun.objects.select_related("initiated_by"), id=run_id)
    logs = list(job_run.logs.all().order_by("ts"))
    confirmations = job_run.teacher_confirmations.all().order_by("-confirmed_at")

    summary_payload = None
    pipeline_steps = []
    artifacts_payload = {}
    errors_payload = []
    if isinstance(job_run.result_json, dict):
        possible_summary = job_run.result_json.get("summary")
        if isinstance(possible_summary, dict):
            summary_payload = possible_summary

        possible_steps = job_run.result_json.get("pipeline_steps")
        if isinstance(possible_steps, list):
            pipeline_steps = possible_steps

        possible_artifacts = job_run.result_json.get("artifacts")
        if isinstance(possible_artifacts, dict):
            artifacts_payload = possible_artifacts

        possible_errors = job_run.result_json.get("errors")
        if isinstance(possible_errors, list):
            errors_payload = possible_errors

    step_rows = _build_step_rows(job_run, logs, pipeline_steps, errors_payload)
    problem_step = _resolve_problem_step(step_rows)
    issues = _extract_issues_payload(job_run)
    filtered_issues = _apply_issue_filters(issues, request)
    return render(
        request,
        "jobs/jobrun_detail.html",
        {
            "job_run": job_run,
            "job_status_meta": _status_meta(job_run.status),
            "logs": logs,
            "back_query": request.GET.urlencode(),
            "result_summary": summary_payload,
            "pipeline_steps": pipeline_steps,
            "step_rows": step_rows,
            "problem_step": problem_step,
            "artifacts_payload": artifacts_payload,
            "errors_payload": errors_payload,
            "confirmations": confirmations,
            "issues": filtered_issues,
            "issue_filters": {
                "code": request.GET.get("code", ""),
                "teacher": request.GET.get("teacher", ""),
                "class_code": request.GET.get("class_code", ""),
                "subject_name": request.GET.get("subject_name", ""),
            },
        },
    )

class _Echo:
    def write(self, value):
        return value


@login_required
@permission_required_403("jobs.view_jobrun", message="Доступ запрещён: нет прав на экспорт issues.")
def export_run_issues_json(request, run_id):
    job_run = get_object_or_404(JobRun, id=run_id)
    issues = _apply_issue_filters(_extract_issues_payload(job_run), request)
    body = json.dumps(issues, ensure_ascii=False, indent=2)
    response = HttpResponse(body, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="run-{job_run.id}-issues.json"'
    return response


@login_required
@permission_required_403("jobs.view_jobrun", message="Доступ запрещён: нет прав на экспорт issues.")
def export_run_issues_csv(request, run_id):
    job_run = get_object_or_404(JobRun, id=run_id)
    issues = _apply_issue_filters(_extract_issues_payload(job_run), request)

    writer = csv.DictWriter(_Echo(), fieldnames=ISSUES_EXPORT_COLUMNS)

    def row_iter():
        yield "\ufeff"
        yield writer.writerow({column: column for column in ISSUES_EXPORT_COLUMNS})
        for issue in issues:
            yield writer.writerow(_normalize_issue_row(issue))

    response = StreamingHttpResponse(row_iter(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="run-{job_run.id}-issues.csv"'
    return response

@login_required
@require_POST
@permission_required_403("jobs.run_full_pipeline", message="Доступ запрещён: нельзя запускать полный пайплайн.")
def run_full_pipeline_view(request):
    job_run = run_full_pipeline(initiated_by=request.user if request.user.is_authenticated else None)
    return redirect("job_run_detail", run_id=job_run.id)

@login_required
@require_POST
@permission_required_403("jobs.send_reminders", message="Доступ запрещён: нельзя отправлять напоминания.")
def send_reminders_view(request, run_id):
    source_job_run = get_object_or_404(JobRun, id=run_id)
    reminder_job_run = run_validation_reminders_job(
        source_job_run=source_job_run,
        initiated_by=request.user if request.user.is_authenticated else None,
    )
    result = (reminder_job_run.result_json or {}).get("summary", {})
    messages.success(
        request,
        (
            "Уведомления учителям отправлены. "
            f"sent={result.get('sent', 0)}, skipped={result.get('skipped', 0)}, errors={result.get('errors', 0)}"
        ),
    )
    return redirect("job_run_detail", run_id=reminder_job_run.id)

@login_required
@require_POST
@permission_required_403("jobs.run_check_missing_data", message="Доступ запрещён: нельзя запускать проверку незаполненности.")
def run_missing_data_check_view(request):
    job_run = run_check_missing_data_job(initiated_by=request.user if request.user.is_authenticated else None)
    return redirect("job_run_detail", run_id=job_run.id)