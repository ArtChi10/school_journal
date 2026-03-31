from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


ROLE_PERMISSIONS = {
    "admin": [
        "jobs.view_jobrun",
        "jobs.run_validation",
        "jobs.run_full_pipeline",
        "jobs.send_reminders",
"jobs.run_check_missing_data",
        "journal_links.view_classsheetlink",
        "journal_links.add_classsheetlink",
        "journal_links.change_classsheetlink",
        "journal_links.delete_classsheetlink",
        "notifications.view_teachercontact",
        "notifications.add_teachercontact",
        "notifications.change_teachercontact",
        "notifications.delete_teachercontact",
    ],
    "vice_principal": [
        "jobs.view_jobrun",
        "jobs.run_validation",
"jobs.run_check_missing_data",
        "journal_links.view_classsheetlink",
    ],
    "operator": [
        "jobs.view_jobrun",
        "jobs.send_reminders",
        "journal_links.view_classsheetlink",
    ],
}


class Command(BaseCommand):
    help = "Create/update RBAC groups (admin, vice_principal, operator) with required permissions"

    def handle(self, *args, **options):
        for role_name, permission_codes in ROLE_PERMISSIONS.items():
            group, _ = Group.objects.get_or_create(name=role_name)
            perms = []
            for code in permission_codes:
                app_label, codename = code.split('.', 1)
                perm = Permission.objects.get(content_type__app_label=app_label, codename=codename)
                perms.append(perm)
            group.permissions.set(perms)
            self.stdout.write(self.style.SUCCESS(f"Configured group: {role_name} ({len(perms)} permissions)"))