"""Notices for the operator: a backup that failed, was not taken, is missing or damaged, a job that ended
uncertain, and a VM a fault stopped or paused (instances.jobs.watch_faults). alert() queues one in the
caller's transaction, so a failed send never holds up the change it tells of; send(), a periodic task of the
worker, mails it to the Settings page's alert addresses and POSTs it as JSON to its alert webhook, trying again
at the next passes."""

import json
import logging
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone, translation
from django.utils.translation import gettext

from appsettings.models import AppSettings

from .models import Alert
from .utils import safe_text, words

logger = logging.getLogger(__name__)

TRIES = 10  # passes, about a minute apart, before a notice is given up
ROWS = 20  # notices a pass
KEPT = timedelta(days=30)


def channels():
    """(the alert addresses, the webhook URL) of the Settings page."""
    values = dict(AppSettings.objects.filter(key__in=("ALERT_EMAILS", "ALERT_WEBHOOK")).values_list("key", "value"))
    return [a.strip() for a in values.get("ALERT_EMAILS", "").split(",") if a.strip()], values.get("ALERT_WEBHOOK", "").strip()


def alert(subject, text):
    """Queue a notice (subject, text: messages, operations.utils.say); none while no channel is set. It never
    stops the change it tells of: a failure is logged, in a savepoint of the caller's transaction."""
    try:
        with transaction.atomic():
            if any(channels()):
                Alert.objects.create(subject=subject, text=text)
    except Exception:
        logger.exception("queueing an alert failed")


def test():
    """A test notice sent at once to the channels saved: {channel: None when it took it, else the error}."""
    emails, url = channels()
    subject, text = gettext("Test alert"), gettext("WebVirtCloud sends its alerts here.")
    results = {}
    if emails:
        results["mail"] = _attempt(lambda: send_mail(f"WebVirtCloud: {subject}", text, None, emails))
    if url:
        results["webhook"] = _attempt(lambda: _post(url, json.dumps(
            {"subject": subject, "text": f"{subject}\n{text}", "time": timezone.now().isoformat()}).encode()))
    return results


def _attempt(deliver):
    try:
        deliver()
    except Exception as err:
        return safe_text(err)
    return None


def send():
    """The notices not sent yet, oldest first, ROWS a pass. A channel that fails is not tried again in the
    pass, so a server that does not answer holds the worker's periodic pass (and the backup schedules) for
    one timeout at most. Each try is claimed first: a worker that took over meanwhile does not send it
    again. Without a channel set the notices wait (or expire)."""
    emails, url = channels()
    Alert.objects.filter(created_at__lt=timezone.now() - KEPT).delete()
    if not (emails or url):
        return
    down = set()
    with translation.override(settings.LANGUAGE_CODE):
        # the least tried first: notices a channel keeps refusing do not hold the new ones back
        for notice in Alert.objects.filter(sent_at__isnull=True, tries__lt=TRIES).order_by("tries", "pk")[:ROWS]:
            wanted = {"mail"} if emails and not notice.mailed else set()
            wanted |= {"webhook"} if url and not notice.posted else set()
            if wanted <= down:
                continue  # its channels failed in this pass: not a try of its own
            if not Alert.objects.filter(pk=notice.pk, tries=notice.tries).update(tries=notice.tries + 1):
                continue
            subject, text, errors = words(notice.subject), words(notice.text), []
            if emails and not notice.mailed:
                errors += _try("mail", down, notice, lambda: send_mail(f"WebVirtCloud: {subject}", text, None, emails))
            if url and not notice.posted:
                body = json.dumps({"subject": subject, "text": f"{subject}\n{text}",
                                   "time": notice.created_at.isoformat()}).encode()
                errors += _try("webhook", down, notice, lambda: _post(url, body))
            done = (not emails or notice.mailed) and (not url or notice.posted)
            Alert.objects.filter(pk=notice.pk).update(error="; ".join(errors))
            if done:  # never undone: a worker that took over may have sent it meanwhile
                Alert.objects.filter(pk=notice.pk).update(sent_at=timezone.now())
            if not done and notice.tries + 1 >= TRIES:
                logger.error("alert %s given up: %s", notice.pk, "; ".join(errors))


def _try(channel, down, notice, deliver):
    """Deliver notice by channel (mail, webhook) and record it: [] when done, [the error] otherwise."""
    if channel in down:
        return [f"{channel}: failed earlier in this pass"]
    try:
        deliver()
    except Exception as err:
        down.add(channel)
        return [f"{channel}: {safe_text(err)}"]
    field = "mailed" if channel == "mail" else "posted"
    setattr(notice, field, True)
    Alert.objects.filter(pk=notice.pk).update(**{field: True})
    return []


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # urllib would follow with a GET without the body: a redirect is an error


def _post(url, body):
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.build_opener(_NoRedirect).open(request, timeout=10):
        pass
