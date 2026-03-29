from django.urls import path

from .views import (
    export_run_issues_csv,
    export_run_issues_json,
    job_run_detail,
    list_job_runs,
    run_full_pipeline_view,
    send_reminders_view,
)

app_name = "jobs"

urlpatterns = [
    path("runs/full-pipeline/start/", run_full_pipeline_view, name="run_full_pipeline"),
    path("runs/", list_job_runs, name="job_run_list"),
    path("runs/<uuid:run_id>/", job_run_detail, name="job_run_detail"),
    path("runs/<uuid:run_id>/export/issues.json", export_run_issues_json, name="export_run_issues_json"),
    path("runs/<uuid:run_id>/export/issues.csv", export_run_issues_csv, name="export_run_issues_csv"),
    path("runs/<uuid:run_id>/send-reminders/", send_reminders_view, name="send_reminders"),
]