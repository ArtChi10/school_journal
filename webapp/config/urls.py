from django.contrib import admin
from django.urls import path

from journal.views import healthcheck, run_pipeline

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthcheck, name="healthz"),
    path("api/run-pipeline", run_pipeline, name="run_pipeline"),
]