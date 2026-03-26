from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import ClassSheetLinkForm
from .models import ClassSheetLink


def list_links(request):
    links = ClassSheetLink.objects.all()
    return render(request, "journal_links/list.html", {"links": links})


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
        {"form": form, "title": "Create class sheet link", "submit_label": "Create"},
    )


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
        {"form": form, "title": "Edit class sheet link", "submit_label": "Save"},
    )


@require_POST
def disable_link(request, pk):
    link = get_object_or_404(ClassSheetLink, pk=pk)
    link.is_active = False
    link.save(update_fields=["is_active", "updated_at"])
    return redirect("journal_links:list_links")