from django.urls import path

from .views import criteria_table

app_name = "pipeline"

urlpatterns = [
    path("criteria-table/", criteria_table, name="criteria_table"),
]