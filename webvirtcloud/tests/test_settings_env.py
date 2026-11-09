"""Settings read from the environment. Each case imports the settings in a
subprocess, so the environment of one case cannot leak into another."""

import json
import os
import subprocess
import sys
import tempfile

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

# Env vars that change the settings; removed from the inherited environment so
# every case starts from the defaults.
CONFIG_VARS = [
    "WEBVIRTCLOUD_HTTPS", "WEBVIRTCLOUD_DEBUG", "WEBVIRTCLOUD_SERIAL_CONSOLE", "ALLOWED_HOSTS",
    "EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "EMAIL_USE_TLS",
    "WEBVIRTCLOUD_DB_HOST", "WEBVIRTCLOUD_DB_PORT", "WEBVIRTCLOUD_DB_NAME",
    "WEBVIRTCLOUD_DB_USER", "WEBVIRTCLOUD_DB_PASSWORD", "TZ",
]


def _env(env):
    base = {k: v for k, v in os.environ.items() if k not in CONFIG_VARS}
    return {**base, "DJANGO_SETTINGS_MODULE": "webvirtcloud.settings", **env}


def load_settings(env, names):
    code = (
        "import json, django; django.setup(); from django.conf import settings as s; "
        f"print(json.dumps({{n: getattr(s, n) for n in {names!r}}}, default=str))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], env=_env(env), cwd=settings.BASE_DIR,
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def run_manage(env, *args):
    result = subprocess.run(
        [sys.executable, "manage.py", *args], env=_env(env), cwd=settings.BASE_DIR,
        capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise AssertionError(output)
    return output


# TestCase: the request cases may touch the database (sessions, axes).
class HttpsProfileTestCase(TestCase):
    def test_https_profile_passes_deploy_checks(self):
        output = run_manage({"WEBVIRTCLOUD_HTTPS": "1"}, "check", "--deploy")
        for check_id in ("security.W004", "security.W008", "security.W012", "security.W016"):
            self.assertNotIn(check_id, output)

    def test_plain_http_is_the_default(self):
        names = ["SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE", "SECURE_SSL_REDIRECT", "SECURE_HSTS_SECONDS"]
        self.assertEqual(load_settings({}, names), dict.fromkeys(names[:3], False) | {"SECURE_HSTS_SECONDS": 0})

    def test_datasource_is_not_redirected(self):
        exempt = load_settings({"WEBVIRTCLOUD_HTTPS": "1"}, ["SECURE_REDIRECT_EXEMPT"])["SECURE_REDIRECT_EXEMPT"]
        with override_settings(SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=exempt):
            self.assertNotEqual(self.client.get("/datasource/openstack/").status_code, 301)
            response = self.client.get("/accounts/login/")
            self.assertEqual(response.status_code, 301)
            self.assertTrue(response["Location"].startswith("https://"))

    def test_proxied_https_request_is_not_redirected(self):
        # TLS ends at a proxy, which tells Django through X-Forwarded-Proto
        with override_settings(SECURE_SSL_REDIRECT=True):
            response = self.client.get("/accounts/login/", HTTP_X_FORWARDED_PROTO="https")
            self.assertNotEqual(response.status_code, 301)


class AllowedHostsTestCase(SimpleTestCase):
    def hosts(self, env):
        return load_settings(env, ["ALLOWED_HOSTS"])["ALLOWED_HOSTS"]

    def test_allowed_hosts_default_is_not_any_host(self):
        hosts = self.hosts({})
        self.assertNotIn("*", hosts)
        self.assertIn("localhost", hosts)

    def test_allowed_hosts_extended_from_env(self):
        hosts = self.hosts({"ALLOWED_HOSTS": " wvc.example.com, ,192.0.2.10 "})
        self.assertEqual(hosts[-2:], ["wvc.example.com", "192.0.2.10"])

    def test_allowed_hosts_star_escape(self):
        self.assertIn("*", self.hosts({"ALLOWED_HOSTS": "*"}))

    def test_a_network_stops_the_start(self):
        with self.assertRaisesRegex(AssertionError, "not networks: 192.0.2.0/24"):
            self.hosts({"ALLOWED_HOSTS": "wvc.example.com,192.0.2.0/24"})


class EmailEnvTestCase(SimpleTestCase):
    def test_email_from_env(self):
        names = ["EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "EMAIL_USE_TLS"]
        env = {"EMAIL_HOST": "smtp.example.com", "EMAIL_PORT": "25", "EMAIL_HOST_USER": "wvc",
               "EMAIL_HOST_PASSWORD": "secret", "EMAIL_USE_TLS": "0"}
        self.assertEqual(load_settings(env, names), {
            "EMAIL_HOST": "smtp.example.com", "EMAIL_PORT": 25, "EMAIL_HOST_USER": "wvc",
            "EMAIL_HOST_PASSWORD": "secret", "EMAIL_USE_TLS": False,
        })


class DatabaseEnvTestCase(SimpleTestCase):
    def db(self, env):
        return load_settings(env, ["DATABASES"])["DATABASES"]["default"]

    def test_sqlite_is_the_default(self):
        db = self.db({})
        self.assertEqual(db["ENGINE"], "django.db.backends.sqlite3")
        self.assertTrue(db["NAME"].endswith("db.sqlite3"))

    def test_postgres_from_env(self):
        db = self.db({"WEBVIRTCLOUD_DB_HOST": "db.example.com", "WEBVIRTCLOUD_DB_PORT": "6432",
                      "WEBVIRTCLOUD_DB_NAME": "wvc", "WEBVIRTCLOUD_DB_USER": "wvcuser",
                      "WEBVIRTCLOUD_DB_PASSWORD": "secret"})
        self.assertEqual(
            {k: db[k] for k in ("ENGINE", "HOST", "PORT", "NAME", "USER", "PASSWORD")},
            {"ENGINE": "django.db.backends.postgresql", "HOST": "db.example.com", "PORT": "6432",
             "NAME": "wvc", "USER": "wvcuser", "PASSWORD": "secret"},
        )

    def test_postgres_connects_within_a_bounded_time(self):
        self.assertEqual(self.db({"WEBVIRTCLOUD_DB_HOST": "db.example.com"})["OPTIONS"], {"connect_timeout": 5})

    def test_postgres_defaults(self):
        db = self.db({"WEBVIRTCLOUD_DB_HOST": "db.example.com"})
        self.assertEqual(
            {k: db[k] for k in ("ENGINE", "PORT", "NAME", "USER", "PASSWORD")},
            {"ENGINE": "django.db.backends.postgresql", "PORT": "5432",
             "NAME": "webvirtcloud", "USER": "webvirtcloud", "PASSWORD": ""},
        )


class DebugEnvTestCase(SimpleTestCase):
    def test_debug_is_off_unless_asked(self):
        self.assertFalse(load_settings({}, ["DEBUG"])["DEBUG"])
        self.assertFalse(load_settings({"WEBVIRTCLOUD_DEBUG": "0"}, ["DEBUG"])["DEBUG"])
        self.assertTrue(load_settings({"WEBVIRTCLOUD_DEBUG": "1"}, ["DEBUG"])["DEBUG"])

    def test_debug_loads_the_urls(self):
        run_manage({"WEBVIRTCLOUD_DEBUG": "1"}, "check")


class EnvFlagTestCase(SimpleTestCase):
    FLAGS = {"WEBVIRTCLOUD_DEBUG": "DEBUG", "WEBVIRTCLOUD_HTTPS": "SESSION_COOKIE_SECURE",
             "WEBVIRTCLOUD_SERIAL_CONSOLE": "SERIAL_CONSOLE_ENABLED", "EMAIL_USE_TLS": "EMAIL_USE_TLS"}

    def test_a_flag_is_1_or_0_unset_is_its_default_and_empty_is_off(self):
        for var, name in self.FLAGS.items():
            with self.subTest(var):
                self.assertTrue(load_settings({var: "1"}, [name])[name])
                self.assertFalse(load_settings({var: "0"}, [name])[name])
                self.assertFalse(load_settings({var: ""}, [name])[name])
                self.assertEqual(load_settings({}, [name])[name], var == "EMAIL_USE_TLS")

    def test_another_value_stops_the_start(self):
        for var in self.FLAGS:
            with self.subTest(var), self.assertRaisesRegex(AssertionError, f"{var} must be 1 or 0, not 'true'"):
                load_settings({var: "true"}, ["DEBUG"])


class LogFileEnvTestCase(SimpleTestCase):
    def log_file(self, env):
        return load_settings(env, ["WEBVIRTCLOUD_LOG_FILE"])["WEBVIRTCLOUD_LOG_FILE"]

    def test_a_relative_log_file_is_in_the_panel_directory(self):
        self.assertEqual(self.log_file({"WEBVIRTCLOUD_LOG_FILE": "data/panel.log"}), str(settings.BASE_DIR / "data" / "panel.log"))

    def test_the_default_and_an_absolute_log_file(self):
        self.assertEqual(self.log_file({"WEBVIRTCLOUD_LOG_FILE": ""}), str(settings.BASE_DIR / "data" / "webvirtcloud.log"))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.log_file({"WEBVIRTCLOUD_LOG_FILE": f"{tmp}/w.log"}), f"{tmp}/w.log")


class TimeZoneEnvTestCase(SimpleTestCase):
    def test_time_zone_from_tz_or_utc(self):
        self.assertEqual(load_settings({}, ["TIME_ZONE"])["TIME_ZONE"], "UTC")
        self.assertEqual(load_settings({"TZ": "Europe/Istanbul"}, ["TIME_ZONE"])["TIME_ZONE"], "Europe/Istanbul")
        self.assertEqual(load_settings({"TZ": ":/etc/localtime"}, ["TIME_ZONE"])["TIME_ZONE"], "UTC")
