from django.contrib import admin

from .models import CriterionEntry, ValidCriterionTemplate


@admin.register(CriterionEntry)
class CriterionEntryAdmin(admin.ModelAdmin):
    list_display = (
        "class_code",
        "subject_name",
        "module_number",
        "teacher_name",
        "source_sheet_name",
        "updated_at",
    )
    list_filter = ("class_code", "subject_name", "module_number", "teacher_name")
    search_fields = (
        "class_code",
        "subject_name",
        "teacher_name",
        "criterion_text",
        "criterion_text_ai",
        "source_sheet_name",
        "source_workbook",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(ValidCriterionTemplate)
class ValidCriterionTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "normalized_name", "is_active", "created_by", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "normalized_name")
    readonly_fields = ("normalized_name", "created_at", "updated_at")