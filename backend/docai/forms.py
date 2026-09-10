"""Admin forms and widgets for editing structured configuration."""
import json

from django import forms
from django.forms.fields import InvalidJSONInput
from unfold.widgets import UnfoldAdminTextareaWidget

from docai.models import WorkflowConfiguration


class PrettyJSONField(forms.JSONField):
    def prepare_value(self, value):
        # Preserve invalid submissions so validation errors never discard edits.
        if isinstance(value, InvalidJSONInput):
            return value
        return json.dumps(value, cls=self.encoder, ensure_ascii=False, indent=2)


class PrettyJSONWidget(UnfoldAdminTextareaWidget):
    def __init__(self, attrs=None):
        super().__init__(attrs={
            "class": "docai-json-editor",
            "spellcheck": "false",
            "autocapitalize": "off",
            "autocomplete": "off",
            "wrap": "off",
            **(attrs or {}),
        })

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        text = context["widget"]["value"] or ""
        context["widget"]["attrs"]["rows"] = max(6, min(24, text.count("\n") + 2))
        return context


class WorkflowConfigurationAdminForm(forms.ModelForm):
    class Meta:
        model = WorkflowConfiguration
        fields = "__all__"
        field_classes = {"config": PrettyJSONField}
        widgets = {"config": PrettyJSONWidget}
