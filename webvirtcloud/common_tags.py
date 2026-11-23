import re

from django import template
from django.utils import formats
from django.utils.translation import gettext

register = template.Library()


@register.simple_tag
def app_active(request, app_name):
    # resolver_match is None on error pages such as 404
    match = request.resolver_match
    return "active" if match and match.app_name == app_name else ""


@register.simple_tag
def view_active(request, view_name):
    match = request.resolver_match
    return "active" if match and match.view_name == view_name else ""


@register.simple_tag
def class_active(request, pattern):
    # Not sure why 'class="active"' returns class=""active""
    return "active" if re.search(pattern, request.path) else ""




BINARY_UNITS = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")


@register.filter
def binary_size(value):
    """A size in bytes with the binary unit the forms ask in: 1536 -> 1.5 KiB, 2 GiB -> 2 GiB."""
    size, unit = float(value or 0), 0
    while abs(round(size, 1)) >= 1024 and unit < len(BINARY_UNITS) - 1:
        size, unit = size / 1024, unit + 1
    size = round(size, 1)
    return f"{formats.number_format(size, 0 if size.is_integer() else 1)}\xa0{BINARY_UNITS[unit]}"


@register.filter
def percent(value):
    """A percentage as the page's language writes it: 13% in English, %13 in Turkish."""
    return gettext("%(percent)s%%") % {"percent": formats.number_format(value)}
