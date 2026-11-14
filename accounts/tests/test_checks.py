from django.conf import settings
from django.test import SimpleTestCase, override_settings

from accounts.checks import login_required_middleware_check

OLD = "login_required.middleware.LoginRequiredMiddleware"
NEW = "django.contrib.auth.middleware.LoginRequiredMiddleware"


class LoginRequiredMiddlewareCheckTestCase(SimpleTestCase):
    def ids(self, middleware):
        with override_settings(MIDDLEWARE=middleware):
            return [e.id for e in login_required_middleware_check(None)]

    def test_current_settings_pass(self):
        self.assertEqual(self.ids(settings.MIDDLEWARE), [])

    def test_settings_from_before_django_5_2_are_rejected(self):
        old = [OLD if m == NEW else m for m in settings.MIDDLEWARE]
        self.assertEqual(self.ids(old), ["accounts.E002"])

    def test_missing_login_middleware_is_rejected(self):
        self.assertEqual(self.ids([m for m in settings.MIDDLEWARE if m != NEW]), ["accounts.E002"])
