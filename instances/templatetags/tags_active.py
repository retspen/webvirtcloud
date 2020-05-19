from django import template
import re

register = template.Library()


@register.simple_tag
def class_active(request, pattern):
    if re.search(pattern, request.path):
        return "active"
    return ''
