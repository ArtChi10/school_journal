import csv
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from admin_panel.authz import permission_required_403
from pipeline.audit import log_criterion_event
from pipeline.forms import ParentContactForm, ParentContactsImportForm, ValidCriterionTemplateForm
from pipeline.models import CriterionEntry, CriterionReviewEvent, ParentContact, ValidCriterionTemplate
from pipeline.parent_contacts import import_parent_contacts_csv


def _parse_non_empty(value: str | None) -> str | None:
    if value is None:
        return None

    trimmed = value.strip()
    return trimmed or None


def _is_admin_role(user) -> bool:
    return bool(user.is_superuser or user.groups.filter(name="admin").exists())


@login_required
@permission_required_403("pipeline.view_criterionentry", message="Доступ запрещён: нет прав на просмотр таблицы критериев.")
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
    validation_status = _parse_non_empty(request.GET.get("validation_status"))
    if validation_status:
        queryset = queryset.filter(validation_status=validation_status)
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
            "status_choices": CriterionEntry.ValidationStatus.choices,
            "filters": {
                "class_code": class_code or "",
                "teacher_name": teacher_name or "",
                "subject_name": subject_name or "",
                "module_number": module_number or "",
                "validation_status": validation_status or "",
            },
            "querystring": preserved_query.urlencode(),
        },
    )

@login_required
@permission_required_403(
    "pipeline.view_criterionentry",
    message="Доступ запрещён: нет прав на просмотр проблемных критериев.",
)
def criteria_failures(request):
    queryset = CriterionEntry.objects.filter(
        validation_status=CriterionEntry.ValidationStatus.INVALID,
        needs_recheck=True,
    ).order_by("class_code", "teacher_name", "subject_name", "module_number", "criterion_text")

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

    status = _parse_non_empty(request.GET.get("status"))
    if status:
        queryset = queryset.filter(ai_verdict=status)

    export_format = _parse_non_empty(request.GET.get("export"))
    if export_format == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="criteria_failures.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "class_code",
                "teacher_name",
                "subject_name",
                "module_number",
                "criterion_text",
                "ai_verdict",
                "ai_comment_or_fix",
                "id",
            ]
        )
        for row in queryset:
            writer.writerow(
                [
                    row.class_code,
                    row.teacher_name,
                    row.subject_name,
                    row.module_number,
                    row.criterion_text,
                    row.ai_verdict,
                    f"{row.ai_why} / {row.ai_fix_suggestion}",
                    row.id,
                ]
            )
        return response

    if export_format == "json":
        payload = [
            {
                "class_code": row.class_code,
                "teacher_name": row.teacher_name,
                "subject_name": row.subject_name,
                "module_number": row.module_number,
                "criterion_text": row.criterion_text,
                "ai_verdict": row.ai_verdict,
                "ai_comment_or_fix": f"{row.ai_why} / {row.ai_fix_suggestion}",
                "id": row.id,
            }
            for row in queryset
        ]
        return JsonResponse(payload, safe=False)

    class_counters = (
        queryset.values("class_code")
        .annotate(total_invalid=Count("id"))
        .order_by("-total_invalid", "class_code")
    )
    teacher_counters = (
        queryset.values("teacher_name")
        .annotate(total_invalid=Count("id"))
        .order_by("-total_invalid", "teacher_name")
    )

    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    preserved_query = request.GET.copy()
    preserved_query.pop("page", None)
    preserved_query.pop("export", None)
    query_without_export = preserved_query.urlencode()

    return render(
        request,
        "pipeline/criteria_failures.html",
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
            "status_choices": queryset.values_list("ai_verdict", flat=True).exclude(ai_verdict="").distinct().order_by("ai_verdict"),
            "filters": {
                "class_code": class_code or "",
                "teacher_name": teacher_name or "",
                "subject_name": subject_name or "",
                "module_number": module_number or "",
                "status": status or "",
            },
            "class_counters": class_counters,
            "teacher_counters": teacher_counters,
            "querystring": query_without_export,
            "can_override": _is_admin_role(request.user),
        },
    )

@login_required
@permission_required_403("pipeline.view_criterionentry", message="Доступ запрещён: нет прав на просмотр критерия.")
def criterion_detail(request, pk):
    criterion = get_object_or_404(CriterionEntry, pk=pk)
    events = criterion.review_events.all().order_by("created_at", "id")
    export_format = _parse_non_empty(request.GET.get("export"))

    if export_format == "json":
        payload = [
            {
                "when": event.created_at.isoformat(),
                "event_type": event.event_type,
                "actor_name": event.actor_name,
                "actor_role": event.actor_role,
                "reason": event.reason,
                "payload": event.payload_json,
            }
            for event in events
        ]
        return JsonResponse(payload, safe=False)

    if export_format == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="criterion_{criterion.id}_history.csv"'
        writer = csv.writer(response)
        writer.writerow(["when", "event_type", "actor_name", "actor_role", "reason", "payload_json"])
        for event in events:
            writer.writerow(
                [
                    event.created_at.isoformat(),
                    event.event_type,
                    event.actor_name,
                    event.actor_role,
                    event.reason,
                    event.payload_json,
                ]
            )
        return response

    return render(
        request,
        "pipeline/criterion_detail.html",
        {"criterion": criterion, "events": events, "can_override": _is_admin_role(request.user)},
    )


@require_POST
@login_required
@permission_required_403("pipeline.change_criterionentry", message="Доступ запрещён: нельзя менять критерий.")
def override_criterion_valid(request, pk):
    if not _is_admin_role(request.user):
        messages.error(request, "Доступ запрещён: override доступен только роли admin.")
        return HttpResponse("forbidden", status=403)

    criterion = get_object_or_404(CriterionEntry, pk=pk)
    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        messages.error(request, "Причина обязательна для override.")
        return redirect(request.POST.get("next") or "pipeline:criteria_failures")

    criterion.validation_status = CriterionEntry.ValidationStatus.OVERRIDDEN_VALID
    criterion.ai_verdict = "overridden_valid"
    criterion.ai_why = reason
    criterion.needs_recheck = False
    criterion.save(update_fields=["validation_status", "ai_verdict", "ai_why", "needs_recheck", "updated_at"])
    log_criterion_event(
        criterion,
        event_type=CriterionReviewEvent.EventType.OVERRIDDEN_VALID,
        actor_name=request.user.username,
        actor_role="admin",
        reason=reason,
        payload={"new_status": "overridden_valid"},
    )
    messages.success(request, "Критерий помечен как валидный по ручному override.")
    return redirect(request.POST.get("next") or "pipeline:criteria_failures")

@login_required
@permission_required_403("pipeline.view_parentcontact", message="Доступ запрещён: нет прав на просмотр контактов родителей.")
def parent_contacts_list(request):
    queryset = ParentContact.objects.all().order_by("parallel", "student_name")

    parallel = _parse_non_empty(request.GET.get("parallel"))
    if parallel and parallel.isdigit():
        queryset = queryset.filter(parallel=int(parallel))

    student = _parse_non_empty(request.GET.get("student"))
    if student:
        queryset = queryset.filter(student_name__icontains=student)

    email = _parse_non_empty(request.GET.get("email"))
    if email:
        queryset = queryset.filter(Q(parent_email_1__icontains=email) | Q(parent_email_2__icontains=email))

    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    import_form = ParentContactsImportForm()

    return render(
        request,
        "pipeline/parent_contacts_list.html",
        {
            "page_obj": page_obj,
            "filters": {"parallel": parallel or "", "student": student or "", "email": email or ""},
            "import_form": import_form,
        },
    )


@login_required
@permission_required_403("pipeline.add_parentcontact", message="Доступ запрещён: нельзя создавать контакты родителей.")
def parent_contact_create(request):
    if request.method == "POST":
        form = ParentContactForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("pipeline:parent_contacts_list")
    else:
        form = ParentContactForm()

    return render(
        request,
        "pipeline/parent_contacts_form.html",
        {"form": form, "title": "Контакты родителей: создать", "submit_label": "Сохранить"},
    )


@login_required
@permission_required_403("pipeline.change_parentcontact", message="Доступ запрещён: нельзя редактировать контакты родителей.")
def parent_contact_edit(request, pk):
    contact = get_object_or_404(ParentContact, pk=pk)
    if request.method == "POST":
        form = ParentContactForm(request.POST, instance=contact)
        if form.is_valid():
            form.save()
            return redirect("pipeline:parent_contacts_list")
    else:
        form = ParentContactForm(instance=contact)

    return render(
        request,
        "pipeline/parent_contacts_form.html",
        {"form": form, "title": "Контакты родителей: редактировать", "submit_label": "Сохранить"},
    )


@require_POST
@login_required
@permission_required_403("pipeline.change_parentcontact", message="Доступ запрещён: нельзя отключать контакты родителей.")
def parent_contact_disable(request, pk):
    contact = get_object_or_404(ParentContact, pk=pk)
    contact.is_active = False
    contact.save(update_fields=["is_active", "updated_at"])
    return redirect("pipeline:parent_contacts_list")


@require_POST
@login_required
@permission_required_403("pipeline.add_parentcontact", message="Доступ запрещён: нельзя импортировать контакты родителей.")
def parent_contacts_import(request):
    form = ParentContactsImportForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Не удалось загрузить файл импорта.")
        return redirect("pipeline:parent_contacts_list")

    uploaded_file = form.cleaned_data["file"]
    if not uploaded_file.name.lower().endswith(".csv"):
        messages.error(request, "Пока поддерживается только CSV импорт.")
        return redirect("pipeline:parent_contacts_list")

    result = import_parent_contacts_csv(uploaded_file.read())
    for error in result.errors:
        messages.error(request, error)

    messages.success(
        request,
        f"Импорт завершён: created={result.created}, updated={result.updated}, skipped={result.skipped}, errors={len(result.errors)}",
    )
    return redirect("pipeline:parent_contacts_list")


@login_required
@permission_required_403(
    "pipeline.view_validcriteriontemplate",
    message="Доступ запрещён: нет прав на просмотр whitelist критериев.",
)
def valid_criteria_list(request):
    templates = ValidCriterionTemplate.objects.select_related("created_by").order_by("name")
    return render(
        request,
        "pipeline/valid_criteria_list.html",
        {
            "templates": templates,
        },
    )


@login_required
@permission_required_403(
    "pipeline.add_validcriteriontemplate",
    message="Доступ запрещён: нельзя создавать whitelist критерии.",
)
def valid_criterion_create(request):
    if request.method == "POST":
        form = ValidCriterionTemplateForm(request.POST)
        if form.is_valid():
            template = form.save(commit=False)
            template.created_by = request.user
            template.save()
            return redirect("pipeline:valid_criteria_list")
    else:
        form = ValidCriterionTemplateForm()

    return render(
        request,
        "pipeline/valid_criteria_form.html",
        {"form": form, "title": "Whitelist критериев: создать", "submit_label": "Сохранить"},
    )


@login_required
@permission_required_403(
    "pipeline.change_validcriteriontemplate",
    message="Доступ запрещён: нельзя редактировать whitelist критерии.",
)
def valid_criterion_edit(request, pk):
    template = get_object_or_404(ValidCriterionTemplate, pk=pk)
    if request.method == "POST":
        form = ValidCriterionTemplateForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            return redirect("pipeline:valid_criteria_list")
    else:
        form = ValidCriterionTemplateForm(instance=template)

    return render(
        request,
        "pipeline/valid_criteria_form.html",
        {"form": form, "title": "Whitelist критериев: редактировать", "submit_label": "Сохранить"},
    )


@require_POST
@login_required
@permission_required_403(
    "pipeline.change_validcriteriontemplate",
    message="Доступ запрещён: нельзя отключать whitelist критерии.",
)
def valid_criterion_disable(request, pk):
    template = get_object_or_404(ValidCriterionTemplate, pk=pk)
    template.is_active = False
    template.save(update_fields=["is_active", "updated_at"])
    return redirect("pipeline:valid_criteria_list")