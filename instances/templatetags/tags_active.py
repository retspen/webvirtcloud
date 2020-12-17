import re

from django import template

register = template.Library()


@register.simple_tag
def class_active(request, pattern):
    if re.search(pattern, request.path):
        return "active"
    return ''
