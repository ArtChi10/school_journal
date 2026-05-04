from django.urls import path

from .views import (
    create_link,
    disable_link,
    edit_link,
    google_oauth_callback,
    list_links,
    run_link_validation,
    run_missing_data_check,
    start_google_oauth,
)

app_name = "journal_links"

urlpatterns = [
    path("links/", list_links, name="list_links"),
    path("links/new/", create_link, name="create_link"),
    path("links/<int:pk>/edit/", edit_link, name="edit_link"),
    path("links/<int:pk>/disable/", disable_link, name="disable_link"),
    path("links/<int:pk>/validate/", run_link_validation, name="run_link_validation"),
    path("links/check-missing-data/", run_missing_data_check, name="run_missing_data_check"),
    path("links/google/oauth/start/", start_google_oauth, name="start_google_oauth"),
    path("links/google/oauth/callback/", google_oauth_callback, name="google_oauth_callback"),
]
