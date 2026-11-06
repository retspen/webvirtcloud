"""socketiod's refusals, which its page shows in the user's language. Here,
as makemessages reads only .py files and socketiod has no extension."""

from django.utils.translation import gettext_noop

TURNED_OFF = gettext_noop("The serial console is turned off on this server")
NOT_ALLOWED = gettext_noop("The console link has expired, or you may no longer open this console: reload the page")
OPEN_ELSEWHERE = gettext_noop("The console of this VM is open in another window")
TOO_MANY = gettext_noop("Too many consoles are open on this server: try again later")
