from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from admin_panel.authz import permission_required_403
from validation.job_runner import run_validation_job

from .forms import ClassSheetLinkForm
from .models import ClassSheetLink

@login_required
@permission_required_403("journal_links.view_classsheetlink", message="Доступ запрещён: нет прав на просмотр ссылок классов.")
def list_links(request):
    links = ClassSheetLink.objects.all()
    return render(request, "journal_links/list.html", {"links": links})

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