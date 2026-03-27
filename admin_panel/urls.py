from django.contrib import admin
from django.urls import include, path
from jobs.views import job_run_detail, list_job_runs
from notifications.views import telegram_webhook

urlpatterns = [
    path("admin/", admin.site.urls),
    path("telegram/webhook/", telegram_webhook, name="telegram_webhook"),
    path("", include("journal_links.urls")),
    path("runs/", list_job_runs, name="job_run_list"),
    path("runs/<uuid:run_id>/", job_run_detail, name="job_run_detail"),
]
