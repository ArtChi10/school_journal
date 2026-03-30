from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from admin_panel.authz import permission_required_403
from pipeline.forms import ParentContactForm, ParentContactsImportForm
from pipeline.models import CriterionEntry, ParentContact
from pipeline.parent_contacts import import_parent_contacts_csv


def _parse_non_empty(value: str | None) -> str | None:
    if value is None:
        return None

    trimmed = value.strip()
    return trimmed or None

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