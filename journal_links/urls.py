from django.urls import path

from .views import create_link, disable_link, edit_link, list_links, run_link_validation

app_name = "journal_links"

urlpatterns = [
    path("links/", list_links, name="list_links"),
    path("links/new/", create_link, name="create_link"),
    path("links/<int:pk>/edit/", edit_link, name="edit_link"),
    path("links/<int:pk>/disable/", disable_link, name="disable_link"),
    path("links/<int:pk>/validate/", run_link_validation, name="run_link_validation"),
]