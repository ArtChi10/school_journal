from django.urls import path

from .views import (
    criteria_failures,
    criterion_detail,
    override_criterion_valid,
    criteria_table,
    parent_contact_create,
    parent_contact_disable,
    parent_contact_edit,
    parent_contacts_import,
    parent_contacts_list,
    valid_criteria_list,
    valid_criterion_create,
    valid_criterion_disable,
    valid_criterion_edit,
)

app_name = "pipeline"

urlpatterns = [
    path("criteria-table/", criteria_table, name="criteria_table"),
    path("criteria-failures/", criteria_failures, name="criteria_failures"),
    path("criteria/<int:pk>/", criterion_detail, name="criterion_detail"),
    path("criteria/<int:pk>/override-valid/", override_criterion_valid, name="override_criterion_valid"),
    path("parent-contacts/", parent_contacts_list, name="parent_contacts_list"),
    path("parent-contacts/create/", parent_contact_create, name="parent_contact_create"),
    path("parent-contacts/<int:pk>/edit/", parent_contact_edit, name="parent_contact_edit"),
    path("parent-contacts/<int:pk>/disable/", parent_contact_disable, name="parent_contact_disable"),
    path("parent-contacts/import/", parent_contacts_import, name="parent_contacts_import"),
    path("valid-criteria/", valid_criteria_list, name="valid_criteria_list"),
    path("valid-criteria/create/", valid_criterion_create, name="valid_criterion_create"),
    path("valid-criteria/<int:pk>/edit/", valid_criterion_edit, name="valid_criterion_edit"),
    path("valid-criteria/<int:pk>/disable/", valid_criterion_disable, name="valid_criterion_disable"),
]