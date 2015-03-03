from django import template
import re

register = template.Library()


@register.simple_tag
def class_activebtn(request, pattern):
    if re.search(pattern, request.path):
        return 'btn-primary'
    return ''