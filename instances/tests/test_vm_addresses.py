"""A VM page does not wait for the guest agent, which may take its whole
timeout: its script asks for the addresses once the page has loaded."""

import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

from django.conf import settings

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from libvirt import libvirtError

from computes.models import Compute
from instances.api.serializers import InstanceDetailsSerializer
from instances.models import Instance


class AddressesTestCase(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("ad-admin", "ad@example.com", "x"))
        compute = Compute.objects.create(name="ad", hostname="127.0.0.1:1", login="root", password="", type=1)
        self.instance = Instance.objects.create(compute=compute, name="ad-vm", uuid="aaaaaaaa-1111-2222-3333-555555555555")
        self.url = reverse("instances:nic_addresses", args=[self.instance.id])

    def addresses(self, **proxy):
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.configure_mock(**proxy)
            return self.client.get(self.url).json()

    def test_each_nic_s_addresses_by_mac(self):
        found = {"52:54:10:00:00:01": (["192.0.2.10"], ["2001:db8::10/64"]), "52:54:10:00:00:02": (["192.0.2.20"], None)}
        self.assertEqual(self.addresses(**{"get_addresses.return_value": found}), {
            "52:54:10:00:00:01": {"ipv4": ["192.0.2.10"], "ipv6": ["2001:db8::10/64"]},
            "52:54:10:00:00:02": {"ipv4": ["192.0.2.20"], "ipv6": []}})

    def test_a_host_that_cannot_be_read_gives_none(self):
        self.assertEqual(self.addresses(**{"get_addresses.side_effect": libvirtError("unable to connect")}), {})

    def test_the_api_s_vm_details_keep_each_nic_s_addresses(self):
        nics = [{"mac": "52:54:10:00:00:01", "type": "network"}, {"mac": "52:54:10:00:00:02", "type": "network"}]
        with patch("instances.models.wvmInstance") as wvm, \
                patch.object(Instance, "networks", new_callable=PropertyMock, return_value=nics):
            wvm.return_value.get_addresses.return_value = {"52:54:10:00:00:01": (["192.0.2.10"], None)}
            networks = InstanceDetailsSerializer(self.instance).get_networks(self.instance)
        self.assertEqual(networks, [{"mac": "52:54:10:00:00:01", "type": "network", "ipv4": ["192.0.2.10"], "ipv6": None},
                                    {"mac": "52:54:10:00:00:02", "type": "network", "ipv4": None, "ipv6": None}])


class AddressesScriptTestCase(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_vm_addresses_js(self):
        base = Path(settings.BASE_DIR)
        result = subprocess.run(["node", str(base / "instances/tests/js/vm_addresses.test.js"),
                                 str(base / "static/js/vm_addresses.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
