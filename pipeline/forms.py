from django import forms

from pipeline.models import ParentContact, ValidCriterionTemplate


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
        fields = ["name", "is_active"]
        labels = {
            "name": "Название критерия",
            "is_active": "Активен",
        }