from django.urls import path

from .views import (
    criteria_table,
    parent_contact_create,
    parent_contact_disable,
    parent_contact_edit,
    parent_contacts_import,
    parent_contacts_list,
)

app_name = "pipeline"

urlpatterns = [
    path("criteria-table/", criteria_table, name="criteria_table"),
    path("parent-contacts/", parent_contacts_list, name="parent_contacts_list"),
    path("parent-contacts/create/", parent_contact_create, name="parent_contact_create"),
    path("parent-contacts/<int:pk>/edit/", parent_contact_edit, name="parent_contact_edit"),
    path("parent-contacts/<int:pk>/disable/", parent_contact_disable, name="parent_contact_disable"),
    path("parent-contacts/import/", parent_contacts_import, name="parent_contacts_import"),
]