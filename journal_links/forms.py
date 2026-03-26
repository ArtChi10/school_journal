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

    def clean_google_sheet_url(self):
        url = (self.cleaned_data.get("google_sheet_url") or "").strip()
        parsed = urlparse(url)

        if parsed.scheme != "https" or parsed.netloc != "docs.google.com":
            raise forms.ValidationError(
                "Укажите корректную ссылку Google Sheets вида: "
                "https://docs.google.com/spreadsheets/d/<ID>..."
            )

        if "/spreadsheets/d/" not in parsed.path:
            raise forms.ValidationError(
                "Ссылка должна содержать путь /spreadsheets/d/<ID>."
            )

        return url