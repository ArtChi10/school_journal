from django import forms

from journal_links.forms import validate_google_sheet_url
from journal_links.models import ClassSheetLink
from pipeline.models import AICriteriaReportTarget, ParentContact, ValidCriterionTemplate
from pipeline.services_upload import extract_drive_folder_id, ReviewUploadError


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


class StudentReviewReportsForm(forms.Form):
    class_sheet_link = forms.ModelChoiceField(
        queryset=ClassSheetLink.objects.none(),
        label="Класс",
        empty_label="Выберите активный класс",
    )
    drive_folder_url = forms.CharField(
        label="Ссылка на Google Drive папку",
        max_length=500,
        widget=forms.TextInput(attrs={"placeholder": "https://drive.google.com/drive/folders/..."}),
    )
    module_number = forms.IntegerField(label="Номер модуля", min_value=1)
    module_dates = forms.CharField(
        label="Даты модуля",
        max_length=255,
        widget=forms.TextInput(attrs={"placeholder": "например: 1 сентября - 25 октября"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["class_sheet_link"].queryset = ClassSheetLink.objects.filter(is_active=True).order_by("class_code", "id")
        for field_name in ["class_sheet_link", "drive_folder_url", "module_number", "module_dates"]:
            self.fields[field_name].widget.attrs.setdefault("class", "form-control" if field_name != "class_sheet_link" else "form-select")

    def clean_drive_folder_url(self):
        value = (self.cleaned_data.get("drive_folder_url") or "").strip()
        try:
            extract_drive_folder_id(value)
        except ReviewUploadError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return value
