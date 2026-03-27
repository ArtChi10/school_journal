from django import forms
from urllib.parse import urlparse

from .models import ClassSheetLink


class ClassSheetLinkForm(forms.ModelForm):
    google_sheet_url = forms.URLField(
        max_length=500,
        widget=forms.URLInput(attrs={"placeholder": "https://docs.google.com/spreadsheets/d/..."}),
    )

    class Meta:
        model = ClassSheetLink
        fields = ["class_code", "subject_name", "teacher_name", "google_sheet_url", "is_active"]
        labels = {
            "class_code": "Класс",
            "subject_name": "Предмет",
            "teacher_name": "Учитель",
            "google_sheet_url": "Ссылка на Google Sheet",
            "is_active": "Активна",
        }

    def clean_google_sheet_url(self):
        url = (self.cleaned_data.get("google_sheet_url") or "").strip()
        parsed = urlparse(url)

        path_parts = [part for part in parsed.path.split("/") if part]
        has_valid_spreadsheet_path = (
                len(path_parts) >= 3 and path_parts[0] == "spreadsheets" and path_parts[1] == "d" and bool(
            path_parts[2])
        )
        if not has_valid_spreadsheet_path:
            raise forms.ValidationError(
                "Укажите корректную ссылку Google Sheets вида: "
                "https://docs.google.com/spreadsheets/d/<ID>..."
            )

        if "/spreadsheets/d/" not in parsed.path:
            raise forms.ValidationError(
                "Ссылка должна содержать путь /spreadsheets/d/<ID>."
            )

        return url