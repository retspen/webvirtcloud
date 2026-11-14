"""What an edit form sends back as the state it showed (admin.views.form_seen)."""

from accounts.models import UserAttributes
from logs.audit import snapshot

from admin.views import form_seen, group_snapshot


def user_seen(user):
    attributes, _created = UserAttributes.objects.get_or_create(user=user)
    return form_seen(snapshot(user), snapshot(attributes))


def group_seen(group):
    return form_seen(group_snapshot(group))
