from django.contrib import admin

from .models import TeacherContact


@admin.register(TeacherContact)
class TeacherContactAdmin(admin.ModelAdmin):
    list_display = ("name", "chat_id", "is_active", "registration_token")
    list_filter = ("is_active",)
    search_fields = ("name", "chat_id", "registration_token")
    readonly_fields = ("registration_token",)