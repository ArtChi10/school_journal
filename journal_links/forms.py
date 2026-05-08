from django import forms
from urllib.parse import urlparse

from .models import ClassSheetLink, DescriptorCriteriaCheckSchedule, DescriptorCriteriaReportTarget


def validate_google_sheet_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)

    path_parts = [part for part in parsed.path.split("/") if part]
    has_valid_spreadsheet_path = (
        len(path_parts) >= 3
        and path_parts[0] == "spreadsheets"
        and path_parts[1] == "d"
        and bool(path_parts[2])
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


class ClassSheetLinkForm(forms.ModelForm):
    google_sheet_url = forms.URLField(
        max_length=500,
        widget=forms.URLInput(attrs={"placeholder": "https://docs.google.com/spreadsheets/d/..."}),
    )

    class Meta:
        model = ClassSheetLink
        fields = ["class_code", "google_sheet_url", "is_active"]
        labels = {
            "class_code": "Класс",
            "google_sheet_url": "Ссылка на Google Sheet",
            "is_active": "Активна",
        }
        help_texts = {
            "google_sheet_url": "Нужна ссылка на всю таблицу Google Sheets, не на отдельный лист.",
        }

    def clean_class_code(self):
        return (self.cleaned_data.get("class_code") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        class_code = (cleaned_data.get("class_code") or "").strip()
        is_active = bool(cleaned_data.get("is_active"))

        if class_code and is_active:
            duplicate_links = ClassSheetLink.objects.filter(
                class_code__iexact=class_code,
                is_active=True,
            )
            if self.instance.pk:
                duplicate_links = duplicate_links.exclude(pk=self.instance.pk)

            if duplicate_links.exists():
                raise forms.ValidationError(
                    "Для этого класса уже есть активная ссылка на Google-таблицу. "
                    "Отключите старую ссылку или отредактируйте существующую запись."
                )

        return cleaned_data


    def clean_google_sheet_url(self):
        return validate_google_sheet_url(self.cleaned_data.get("google_sheet_url") or "")


class DescriptorCriteriaReportTargetForm(forms.ModelForm):
    google_sheet_url = forms.URLField(
        max_length=500,
        widget=forms.URLInput(attrs={"placeholder": "https://docs.google.com/spreadsheets/d/..."}),
    )

    class Meta:
        model = DescriptorCriteriaReportTarget
        fields = ["name", "google_sheet_url", "is_active"]
        labels = {
            "name": "Название",
            "google_sheet_url": "Ссылка на Google Spreadsheet отчета",
            "is_active": "Активен",
        }
        help_texts = {
            "google_sheet_url": "Один постоянный Google Spreadsheet, который будет обновляться после проверки.",
        }

    def clean_name(self):
        return (self.cleaned_data.get("name") or "").strip() or "Descriptor criteria report"

    def clean_google_sheet_url(self):
        return validate_google_sheet_url(self.cleaned_data.get("google_sheet_url") or "")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs.setdefault("class", "form-control")
        self.fields["google_sheet_url"].widget.attrs.setdefault("class", "form-control")
        self.fields["is_active"].widget.attrs.setdefault("class", "form-check-input")


class DescriptorCriteriaCheckScheduleForm(forms.ModelForm):
    class Meta:
        model = DescriptorCriteriaCheckSchedule
        fields = ["is_enabled", "interval_minutes"]
        labels = {
            "is_enabled": "Включить автопроверку",
            "interval_minutes": "Интервал, минут",
        }
        help_texts = {
            "interval_minutes": "Минимум 1 минута. Например: 30.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_enabled"].widget.attrs.setdefault("class", "form-check-input")
        self.fields["interval_minutes"].min_value = 1
        self.fields["interval_minutes"].widget.attrs.update(
            {
                "class": "form-control",
                "min": "1",
                "step": "1",
            }
        )
