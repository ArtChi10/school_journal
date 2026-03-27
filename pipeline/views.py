from django.core.paginator import Paginator
from django.shortcuts import render

from .models import CriterionEntry


def _parse_non_empty(value: str | None) -> str | None:
    if value is None:
        return None

    trimmed = value.strip()
    return trimmed or None


def criteria_table(request):
    queryset = CriterionEntry.objects.all().order_by(
        "class_code", "teacher_name", "subject_name", "module_number", "criterion_text"
    )

    class_code = _parse_non_empty(request.GET.get("class_code"))
    if class_code:
        queryset = queryset.filter(class_code=class_code)

    teacher_name = _parse_non_empty(request.GET.get("teacher_name"))
    if teacher_name:
        queryset = queryset.filter(teacher_name=teacher_name)

    subject_name = _parse_non_empty(request.GET.get("subject_name"))
    if subject_name:
        queryset = queryset.filter(subject_name=subject_name)

    module_number = _parse_non_empty(request.GET.get("module_number"))
    if module_number:
        queryset = queryset.filter(module_number=module_number)

    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    preserved_query = request.GET.copy()
    preserved_query.pop("page", None)

    return render(
        request,
        "pipeline/criteria_table.html",
        {
            "page_obj": page_obj,
            "class_choices": CriterionEntry.objects.values_list("class_code", flat=True).distinct().order_by("class_code"),
            "teacher_choices": CriterionEntry.objects.values_list("teacher_name", flat=True)
            .distinct()
            .order_by("teacher_name"),
            "subject_choices": CriterionEntry.objects.values_list("subject_name", flat=True)
            .distinct()
            .order_by("subject_name"),
            "module_choices": CriterionEntry.objects.values_list("module_number", flat=True)
            .distinct()
            .order_by("module_number"),
            "filters": {
                "class_code": class_code or "",
                "teacher_name": teacher_name or "",
                "subject_name": subject_name or "",
                "module_number": module_number or "",
            },
            "querystring": preserved_query.urlencode(),
        },
    )