"""Live check that the secrets page creates a secret for each usage type
with a real usage value: a volume path, an iSCSI IQN and a Ceph name. Runs
only with TEST_LIBVIRT_HOST set."""

import os
import unittest

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.tests import livetest
from vrtManager.connection import connection_manager

P = livetest.PREFIX
USAGES = {
    libvirt.VIR_SECRET_USAGE_TYPE_VOLUME: ("volume", f"/var/lib/libvirt/{P}secrets/vm-1.qcow2"),
    libvirt.VIR_SECRET_USAGE_TYPE_ISCSI: ("iscsi", f"iqn.2026-10.test.wvc:{P}secret"),
    libvirt.VIR_SECRET_USAGE_TYPE_CEPH: ("ceph", f"client.{P}secret secret"),
}


@unittest.skipUnless(livetest.enabled(), "Set TEST_LIBVIRT_HOST to run the live libvirt tests")
class LiveSecretsTestCase(TestCase):
    def setUp(self):
        args = dict(
            hostname=os.environ["TEST_LIBVIRT_HOST"],
            login=os.environ.get("TEST_LIBVIRT_LOGIN", ""),
            password=os.environ.get("TEST_LIBVIRT_PASSWORD", ""),
            type=int(os.environ.get("TEST_LIBVIRT_TYPE", 4)),
        )
        self.conn = connection_manager.get_connection(*args.values())
        self.remove_secrets()
        self.addCleanup(self.remove_secrets)
        self.compute = Compute.objects.create(name="live-secrets", **args)
        self.client.force_login(get_user_model().objects.create_superuser("live-secrets", "ls@example.com", "x"))

    def remove_secrets(self):
        for secret in self.conn.listAllSecrets():
            if (secret.usageType(), secret.usageID()) in {(t, v) for t, (_, v) in USAGES.items()}:
                secret.undefine()

    def test_each_usage_type_takes_a_real_value(self):
        for usage_type, (name, value) in USAGES.items():
            with self.subTest(name):
                response = self.client.post(
                    reverse("virtsecrets", args=[self.compute.id]),
                    {"create": "", "usage_type": name, "usage": value},
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.conn.secretLookupByUsage(usage_type, value).usageID(), value)
