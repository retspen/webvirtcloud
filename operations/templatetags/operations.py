import json
import uuid

from django import template
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.timesince import timesince
from django.utils.translation import ngettext, pgettext_lazy

from operations.jobs import take_remembered
from operations.models import Operation

register = template.Library()

# The Bootstrap colour of each job state, for badges and alerts; job_panel.js has the same map
STATE_COLORS = {
    Operation.QUEUED: "secondary",
    Operation.RUNNING: "primary",
    Operation.CANCELLING: "info",
    Operation.SUCCEEDED: "success",
    Operation.FAILED: "danger",
    Operation.CANCELLED: "secondary",
    Operation.UNCERTAIN: "warning",
}


# What a job's state is called on the pages; the stored state stays the code
STATE_LABELS = {
    Operation.QUEUED: pgettext_lazy("job state", "queued"),
    Operation.RUNNING: pgettext_lazy("job state", "running"),
    Operation.CANCELLING: pgettext_lazy("job state", "cancelling"),
    Operation.SUCCEEDED: pgettext_lazy("job state", "succeeded"),
    Operation.FAILED: pgettext_lazy("job state", "failed"),
    Operation.CANCELLED: pgettext_lazy("job state", "cancelled"),
    Operation.UNCERTAIN: pgettext_lazy("job state", "uncertain"),
}


@register.simple_tag
def submission_key():
    """A new key per rendered form: a resubmitted form returns its job."""
    return format_html('<input type="hidden" name="submission_key" value="{}">', uuid.uuid4().hex)


@register.filter
def state_color(state):
    return STATE_COLORS[state]


@register.filter
def state_label(state):
    return STATE_LABELS[state]


@register.filter
def duration(start, end):
    """The time from start to end, in seconds under a minute: timesince counts minutes.
    Never negative: the worker and the panel may run on hosts whose clocks differ."""
    seconds = max(0, int((end - start).total_seconds()))
    if seconds < 60:
        return ngettext("%(count)d second", "%(count)d seconds", seconds) % {"count": seconds}
    return timesince(start, end)


@register.filter
def wrap_at_slash(label):
    """A "<compute>/<vm>" label that wraps after its slash only, never inside a name."""
    return format_html_join(mark_safe("/<wbr>"), '<span class="text-nowrap">{}</span>', ((part,) for part in label.split("/")))


@register.inclusion_tag("operations/job_panel_script.html", takes_context=True)
def job_panel_script(context, resource):
    """The job panel's script for the page of resource."""
    return {"resource": resource, "csrf_token": context.get("csrf_token"),
            "remembered": json.dumps(take_remembered(context["request"], resource))}
