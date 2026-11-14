"""get_settings() runs on every request (middleware). A database error must not
leave the loop reading an unbound variable (the old bare except did), and must
not crash the request chain over a transient read."""

from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase

from appsettings.models import AppSettings
from appsettings.settings import app_settings, get_settings


class GetSettingsTestCase(TestCase):
    def test_a_database_error_does_not_raise(self):
        app_settings.MARKER = "kept"
        with patch("appsettings.settings.AppSettings.objects") as objects:
            objects.all.side_effect = DatabaseError("db down")
            get_settings()  # must not raise UnboundLocalError or DatabaseError
        self.assertEqual(app_settings.MARKER, "kept")

    def test_settings_are_loaded_when_the_database_works(self):
        AppSettings.objects.update_or_create(key="TEST_MARKER_KEY", defaults={"name": "m", "value": "from-db"})
        try:
            get_settings()
            self.assertEqual(app_settings.TEST_MARKER_KEY, "from-db")
        finally:
            if hasattr(app_settings, "TEST_MARKER_KEY"):
                delattr(app_settings, "TEST_MARKER_KEY")

    def test_a_query_that_fails_during_iteration_does_not_raise(self):
        app_settings.MARKER2 = "kept"
        with patch("appsettings.settings.AppSettings.objects") as objects:
            objects.all.return_value.__iter__.side_effect = DatabaseError("cursor died")
            get_settings()
        self.assertEqual(app_settings.MARKER2, "kept")
