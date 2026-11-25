import uuid
from urllib.parse import quote

from django import template
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.timesince import timesince
from django.utils.translation import gettext, ngettext, pgettext, pgettext_lazy

from operations.jobs import take_remembered
from operations.models import Operation
from operations.utils import words as _words

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
def words(messages):
    """A job's stored messages (operations.utils.say) in the reader's language."""
    return _words(messages)


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


@register.simple_tag
def active_job_count(user):
    """How many of the jobs the user sees are queued, running or cancelling: the menu's Jobs badge."""
    return Operation.visible_to(user).filter(state__in=Operation.ACTIVE).count()


@register.inclusion_tag("operations/job_panel_script.html", takes_context=True)
def job_panel_script(context, resource):
    """The job panel's script for the page of resource."""
    return {"settings": {
        "resource": reverse("operation-resource") + "?key=" + quote(resource, safe=""),
        "jobs": reverse("operation-list"),
        "csrf_token": get_token(context["request"]),
        "remembered": take_remembered(context["request"], resource),
        "states": {state: str(label) for state, label in STATE_LABELS.items()},
        "text": {
            "cancel": gettext("Cancel the job"),
            "cancel_confirm": gettext("Cancel %(job)s? It stops where it is."),
            "open": pgettext("verb", "Open"),
            "refresh": gettext("Refresh"),
            "dismiss": gettext("Dismiss"),
            "finishing": gettext("Finishing…"),
            "not_removed": gettext("Files not removed:"),
            "short_operation": gettext("A short operation is in progress."),
            "worker_gone": gettext("The job worker is not running; it was last seen %(when)s. Jobs wait until it runs again."),
            "worker_never": gettext("The job worker has not run yet. Jobs wait until it runs."),
            "cancel_failed": gettext("Cancel failed (HTTP %(status)s)."),
            "cancel_unreachable": gettext("Cancel failed: the server could not be reached."),
        },
    }}
