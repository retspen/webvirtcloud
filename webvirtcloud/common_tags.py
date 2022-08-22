import re

from django import template

register = template.Library()


@register.simple_tag
def app_active(request, app_name):
    return "active" if request.resolver_match.app_name == app_name else ""


@register.simple_tag
def view_active(request, view_name):
    return "active" if request.resolver_match.view_name == view_name else ""


@register.simple_tag
def class_active(request, pattern):
    # Not sure why 'class="active"' returns class=""active""
    return "active" if re.search(pattern, request.path) else ""


@register.simple_tag
def has_perm(user, permission_codename):
    return bool(user.has_perm(permission_codename))
