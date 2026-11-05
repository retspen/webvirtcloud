"""{% bs_icon %}: a Bootstrap icon's SVG, inline, from static/icon_cache,
which holds each icon a template uses at the size, color and classes it
asks for (webvirtcloud/tests/test_icon_cache.py checks every template)."""

from functools import cache
from pathlib import Path

from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

register = template.Library()

ICONS = Path(settings.BASE_DIR, "static", "icon_cache")


@register.simple_tag
def bs_icon(name, size=None, color=None, extra_classes=None):
    return _svg(f"{name}_{size}_{color}_{extra_classes}.svg".replace(" ", "_"))


@cache  # one file a literal of the templates
def _svg(file_name):
    return mark_safe((ICONS / file_name).read_text(encoding="utf-8"))
