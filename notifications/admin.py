from django.contrib import admin

from .models import TeacherContact


@admin.register(TeacherContact)
class TeacherContactAdmin(admin.ModelAdmin):
    list_display = ("teacher_name", "chat_id", "is_active", "last_seen_at", "registration_token")
    list_filter = ("is_active",)
    search_fields = ("teacher_name", "chat_id", "registration_token")
    readonly_fields = ("registration_token",)