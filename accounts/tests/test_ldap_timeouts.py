"""A login through LDAP waits a bounded time for the directory."""

import unittest

from django.test import SimpleTestCase

try:
    import ldap
    from django_auth_ldap.backend import LDAPBackend
except ImportError:  # LDAP is optional (conf/requirements-ldap.txt)
    ldap = None


@unittest.skipIf(ldap is None, "python-ldap is not installed")
class LdapTimeoutTests(SimpleTestCase):
    def test_the_connection_and_each_answer_have_a_timeout(self):
        # python-ldap's default for both is to wait without end
        options = LDAPBackend().settings.CONNECTION_OPTIONS
        self.assertGreater(options.get(ldap.OPT_NETWORK_TIMEOUT, -1), 0)
        self.assertGreater(options.get(ldap.OPT_TIMEOUT, -1), 0)
