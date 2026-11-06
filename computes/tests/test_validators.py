"""A compute's hostname and login go unquoted into libvirt connection URIs
and an ssh command line; they are validated so neither can inject a URI
parameter (e.g. ?command=, ?no_verify=) or an ssh option."""

import unittest

from django.core.exceptions import ValidationError

from computes.validators import validate_hostname, validate_login


class HostnameValidatorTestCase(unittest.TestCase):
    def test_accepts_ipv4_and_host_names(self):
        for value in ("192.0.2.10", "localhost", "host.example.com", "a-b.example.", "host1"):
            with self.subTest(value=value):
                validate_hostname(value)

    def test_rejects_uri_and_option_injection(self):
        for value in (
            "-x",
            "a b;c",
            "host:2222",
            "192.0.2.1/system?command=/evil.sh&a=",
            "host/system?no_verify=1",
            "qemu+ssh://host/system",
            "2001:db8::1",
            "",
            "host name",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_hostname(value)


class LoginValidatorTestCase(unittest.TestCase):
    def test_accepts_plain_logins_and_empty(self):
        # empty: TCP falls back to server auth, the socket transport ignores it
        for value in ("", "root", "libvirt.user", "user-1", "_svc"):
            with self.subTest(value=value):
                validate_login(value)

    def test_rejects_option_and_delimiter_injection(self):
        for value in ("-oProxyCommand=x", "u@realm", "a/b", "a b", "a\\b", "a%b"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_login(value)


