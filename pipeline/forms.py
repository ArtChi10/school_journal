from django import forms

from journal_links.forms import validate_google_sheet_url
from pipeline.models import AICriteriaReportTarget, ParentContact, ValidCriterionTemplate


class ParentContactForm(forms.ModelForm):
    class Meta:
        model = ParentContact
        fields = [
            "parallel",
            "class_code",
            "student_name",
            "parent_email_1",
            "parent_email_2",
            "is_active",
        ]
        labels = {
            "parallel": "Параллель",
            "class_code": "Класс",
            "student_name": "Ученик",
            "parent_email_1": "Email родителя 1",
            "parent_email_2": "Email родителя 2",
            "is_active": "Активен",
        }


class ParentContactsImportForm(forms.Form):
    file = forms.FileField(label="CSV файл")


class ValidCriterionTemplateForm(forms.ModelForm):
    class Meta:
        model = ValidCriterionTemplate
        fields = ["name", "keep_reason", "is_active"]
        labels = {
            "name": "Название критерия",
            "keep_reason": "Почему оставляем",
            "is_active": "Активен",
        }
        widgets = {
            "keep_reason": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs.setdefault("class", "form-control")
        self.fields["keep_reason"].widget.attrs.setdefault("class", "form-control")
        self.fields["is_active"].widget.attrs.setdefault("class", "form-check-input")


class AICriteriaReportTargetForm(forms.ModelForm):
    google_sheet_url = forms.URLField(
        max_length=500,
        widget=forms.URLInput(attrs={"placeholder": "https://docs.google.com/spreadsheets/d/..."}),
    )

    class Meta:
        model = AICriteriaReportTarget
        fields = ["name", "google_sheet_url", "is_active"]
        labels = {
            "name": "Название",
            "google_sheet_url": "Ссылка на Google Spreadsheet AI-отчета",
            "is_active": "Активен",
        }
        help_texts = {
            "google_sheet_url": "Отдельный Google Spreadsheet, который будет обновляться после AI-вычитки критериев.",
        }

    def clean_name(self):
        return (self.cleaned_data.get("name") or "").strip() or "AI criteria review report"

    def clean_google_sheet_url(self):
        return validate_google_sheet_url(self.cleaned_data.get("google_sheet_url") or "")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs.setdefault("class", "form-control")
        self.fields["google_sheet_url"].widget.attrs.setdefault("class", "form-control")
        self.fields["is_active"].widget.attrs.setdefault("class", "form-check-input")
