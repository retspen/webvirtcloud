"""API token authentication: knox's, noting when each token was last used."""

from datetime import timedelta

from django.utils import timezone
from drf_spectacular.contrib.knox_auth_token import KnoxTokenScheme
from knox.auth import TokenAuthentication as KnoxTokenAuthentication

# a token's last use is written at most once a minute, not on every request
LAST_USED_EVERY = timedelta(minutes=1)


class TokenAuthentication(KnoxTokenAuthentication):
    def validate_user(self, auth_token):
        user, token = super().validate_user(auth_token)
        now = timezone.now()
        if token.last_used is None or now - token.last_used >= LAST_USED_EVERY:
            type(token).objects.filter(pk=token.pk).update(last_used=now)
        return user, token


class TokenScheme(KnoxTokenScheme):
    """The API schema's description of these tokens, as of knox's."""
    target_class = "accounts.auth.TokenAuthentication"
