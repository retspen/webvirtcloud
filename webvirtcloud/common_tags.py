from django import template
import re

register = template.Library()


@register.simple_tag
def app_active(request, app_name):
    if request.resolver_match.app_name == app_name:
        return 'active'
    return ''


@register.simple_tag
def view_active(request, view_name):
    if request.resolver_match.view_name == view_name:
        return 'active'
    return ''


@register.simple_tag
def class_active(request, pattern):
    if re.search(pattern, request.path):
        # Not sure why 'class="active"' returns class=""active""
        return 'active'
    return ''


@register.simple_tag
def has_perm(user, permission_codename):
    if user.has_perm(permission_codename):
        return True
    return False
