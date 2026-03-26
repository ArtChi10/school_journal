from django.contrib import admin

from .models import ClassSheetLink


@admin.register(ClassSheetLink)
class ClassSheetLinkAdmin(admin.ModelAdmin):
    list_display = (
        "class_code",
        "subject_name",
        "teacher_name",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "class_code")
    search_fields = ("class_code", "subject_name", "teacher_name")
    ordering = ("class_code", "subject_name")