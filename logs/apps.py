from django.apps import AppConfig


def _login_row(request, user, message, success):
    from logs.audit import request_ip, write

    write(user, "-", "", message, success, request_ip(request) if request is not None else None)


def logged_in(sender, request, user, **kwargs):
    _login_row(request, user.get_username(), "Login", True)


def login_failed(sender, credentials, request=None, **kwargs):
    _login_row(request, credentials.get("username", ""), "Login failed", False)


def locked_out(sender, request, username, ip_address, **kwargs):
    _login_row(request, username or "", "Locked out", False)


def logged_out(sender, request, user, **kwargs):
    if user is not None:
        _login_row(request, user.get_username(), "Logout", True)


class LogsConfig(AppConfig):
    name = "logs"
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        from axes.signals import user_locked_out
        from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed

        user_logged_in.connect(logged_in, dispatch_uid="logs.login")
        user_login_failed.connect(login_failed, dispatch_uid="logs.login_failed")
        user_locked_out.connect(locked_out, dispatch_uid="logs.locked_out")
        user_logged_out.connect(logged_out, dispatch_uid="logs.logout")
