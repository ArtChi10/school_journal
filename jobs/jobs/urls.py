from django.urls import path

from .views import job_run_detail, list_job_runs, run_full_pipeline_view, send_reminders_view

app_name = "jobs"

urlpatterns = [
    path("runs/full-pipeline/start/", run_full_pipeline_view, name="run_full_pipeline"),
    path("runs/", list_job_runs, name="job_run_list"),
    path("runs/<uuid:run_id>/", job_run_detail, name="job_run_detail"),
    path("runs/<uuid:run_id>/send-reminders/", send_reminders_view, name="send_reminders"),
]