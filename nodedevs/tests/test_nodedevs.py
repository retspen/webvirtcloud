"""The host's devices page: PCI devices by IOMMU group and USB devices, each
with what the host has on it (network interfaces, disks, its graphics card)
and the VMs that name it, by PCI address, by USB address or by USB model
only. Node device XML as libvirt 11.10 writes it; the connection is a mock,
libvirt's test driver has no node devices."""

from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import html
from vrtManager.tests.fakes import NODES, node
from vrtManager.tests.fakes import PCI_0A, USB_1_3, vm


class NodeDevicesPageTests(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="nd", hostname="192.0.2.30", login="root", password="", type=1)
        self.client.force_login(get_user_model().objects.create_superuser("nd", "nd@example.com", "pw"))
        self.url = reverse("nodedevs", args=[self.compute.id])

    def page(self, nodes=NODES, domains=()):
        with patch("vrtManager.connection.connection_manager.get_connection") as get:
            get.return_value.listAllDevices.return_value = [node(*n) for n in nodes]
            get.return_value.listAllDomains.return_value = list(domains)
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return html.fromstring(response.content)

    def test_the_page_groups_pci_devices_and_links_their_vms(self):
        instance = Instance.objects.create(compute=self.compute, name="db-1", uuid="00000000-0000-4000-8000-0000000000d1")
        page = self.page(domains=[vm("db-1", PCI_0A), vm("outside-1", USB_1_3)])
        headers = [" ".join(h.text_content().split()) for h in page.xpath("//tr[@data-group-header]")]
        self.assertEqual(headers, ["IOMMU group 2", "IOMMU group 3", "IOMMU group 4", "Without an IOMMU group"])
        self.assertEqual(page.xpath("//a[text()='db-1']/@href"), [reverse("instances:instance", args=[instance.id])])
        self.assertIn("outside-1", page.text_content())  # a VM the panel does not have: named, not linked
        self.assertNotIn("No IOMMU groups detected", page.text_content())

    def test_a_host_without_iommu_groups_says_so(self):
        page = self.page(nodes=[n for n in NODES if "iommuGroup" not in n[1]])
        self.assertIn("No IOMMU groups detected", page.text_content())

    def test_a_host_without_pci_or_usb_devices_says_so(self):
        page = self.page(nodes=[n for n in NODES if "usb" in n[0]])
        self.assertIn("The host reports no PCI devices.", page.text_content())
        self.assertNotIn("No IOMMU groups detected", page.text_content())  # nothing to give
        self.assertIn("The host reports no USB devices.", self.page(nodes=NODES[:2]).text_content())

    def test_only_superusers(self):
        self.client.force_login(get_user_model().objects.create_user("nd-user", "u@example.com", "pw"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_a_host_not_read_shows_no_device(self):
        # without the VMs' definitions a device would look free
        with patch("vrtManager.connection.connection_manager.get_connection") as get:
            get.return_value.listAllDevices.return_value = [node(*n) for n in NODES]
            get.return_value.listAllDomains.side_effect = libvirt.libvirtError("unreachable")
            response = self.client.get(self.url)
        page = html.fromstring(response.content)
        self.assertEqual(page.xpath("//table"), [])
        self.assertIn("unreachable", page.text_content())
