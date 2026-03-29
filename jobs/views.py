from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from django.views.decorators.http import require_POST

from pipeline.full_pipeline_runner import run_full_pipeline

from .models import JobRun


def _parse_non_empty(value: str | None) -> str | None:
    if value is None:
        return None

    trimmed = value.strip()
    return trimmed or None


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


def job_run_detail(request, run_id):
    job_run = get_object_or_404(JobRun.objects.select_related("initiated_by"), id=run_id)
    logs = job_run.logs.all().order_by("ts")
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

    return render(
        request,
        "jobs/jobrun_detail.html",
        {
            "job_run": job_run,
            "logs": logs,
            "back_query": request.GET.urlencode(),
            "result_summary": summary_payload,
            "pipeline_steps": pipeline_steps,
            "artifacts_payload": artifacts_payload,
            "errors_payload": errors_payload,
            "confirmations": confirmations,
        },
    )

@require_POST
def run_full_pipeline_view(request):
    job_run = run_full_pipeline(initiated_by=request.user if request.user.is_authenticated else None)
    return redirect("job_run_detail", run_id=job_run.id)