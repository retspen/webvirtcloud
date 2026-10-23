"""Marking a field the server refused: its class, the ARIA attributes that
tie it to its message, and the message beside it. A field is a bound form
field; the page renders without forms when the host could not be read, so
anything without errors marks nothing."""

from django import template
from django.utils.html import format_html

register = template.Library()


def _errors(field):
    return getattr(field, "errors", None)


@register.filter
def invalid(field):
    """" is-invalid", to append to the class of a refused field."""
    return " is-invalid" if _errors(field) else ""


@register.simple_tag
def error_attrs(field, input_id, help_id=""):
    """aria-invalid and aria-describedby for a refused field; with help_id,
    the field is described by its help text too, refused or not."""
    described = " ".join(filter(None, [help_id, f"{input_id}_error" if _errors(field) else ""]))
    invalid = format_html(' aria-invalid="true"') if _errors(field) else ""
    return format_html('{} aria-describedby="{}"', invalid, described) if described else ""


@register.simple_tag
def field_error(field, input_id):
    """The field's errors, shown beside it."""
    if not _errors(field):
        return ""
    return format_html('<div class="invalid-feedback" id="{}_error">{}</div>', input_id, " ".join(_errors(field)))
