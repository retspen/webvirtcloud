"""django-bootstrap5's field renderer, marking only the fields in error."""

from django.db.models.fields import BLANK_CHOICE_DASH
from django.forms import ModelChoiceField
from django.utils.translation import gettext_lazy as _
from django_bootstrap5.renderers import FieldRenderer as BootstrapFieldRenderer

DASH = BLANK_CHOICE_DASH[0][1]


class FieldRenderer(BootstrapFieldRenderer):
    """A sent form marks its fields in error red and leaves the others as
    they were: a green "valid" mark on a form that was not saved reads as if
    it had been. A list's empty choice says to choose, not Django's dashes."""

    def __init__(self, field, **kwargs):
        super().__init__(field, **kwargs)
        form_field = getattr(field, "field", None)  # the form's field, its own copy for this form
        if isinstance(form_field, ModelChoiceField):
            if form_field.empty_label == DASH:
                form_field.empty_label = _("Choose…")
        elif any(label == DASH for _value, label in getattr(form_field, "choices", ())):
            form_field.choices = [(value, _("Choose…") if label == DASH else label) for value, label in form_field.choices]

    def get_server_side_validation_classes(self):
        return "is-invalid" if self.field_errors else ""
