from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

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
    job_run = get_object_or_404(JobRun, id=run_id)
    return render(request, "jobs/jobrun_detail.html", {"job_run": job_run})