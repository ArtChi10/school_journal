from django.contrib import admin

from .models import TeacherConfirmation, TeacherContact


@admin.register(TeacherContact)
class TeacherContactAdmin(admin.ModelAdmin):
    list_display = ("teacher_name", "chat_id", "is_active", "last_seen_at", "registration_token")
    list_filter = ("is_active",)
    search_fields = ("teacher_name", "chat_id", "registration_token")
    readonly_fields = ("registration_token",)


@admin.register(TeacherConfirmation)
class TeacherConfirmationAdmin(admin.ModelAdmin):
    list_display = ("teacher_name", "chat_id", "job_run", "status", "confirmed_at")
    list_filter = ("status", "confirmed_at")
    search_fields = ("teacher_name", "chat_id", "job_run__id")
    readonly_fields = ("confirmed_at",)