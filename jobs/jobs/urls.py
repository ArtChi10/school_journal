from django.urls import path

from .views import job_run_detail, list_job_runs

app_name = "jobs"

urlpatterns = [
    path("runs/", list_job_runs, name="job_run_list"),
    path("runs/<uuid:run_id>/", job_run_detail, name="job_run_detail"),
]