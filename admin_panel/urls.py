from django.contrib import admin
from django.urls import path

from notifications.views import telegram_webhook

urlpatterns = [
    path("admin/", admin.site.urls),
    path("telegram/webhook/", telegram_webhook, name="telegram_webhook"),
]