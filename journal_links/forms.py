from django import forms
from django.core.validators import RegexValidator

from .models import ClassSheetLink


google_sheet_url_validator = RegexValidator(
    regex=r"^https?://docs\.google\.com/spreadsheets/d/[a-zA-Z0-9_-]+(?:/.*)?$",
    message=(
        "Enter a valid Google Sheets URL in format "
        "https://docs.google.com/spreadsheets/d/<sheet_id>/..."
    ),
)


class ClassSheetLinkForm(forms.ModelForm):
    google_sheet_url = forms.URLField(
        max_length=500,
        validators=[google_sheet_url_validator],
        widget=forms.URLInput(attrs={"placeholder": "https://docs.google.com/spreadsheets/d/..."}),
    )

    class Meta:
        model = ClassSheetLink
        fields = ["class_code", "subject_name", "teacher_name", "google_sheet_url", "is_active"]