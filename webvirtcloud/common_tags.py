import re

from django import template

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


