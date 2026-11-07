"""A VM's host devices: USB devices of its host given and taken back, each
named once whether the running VM or its next start has it; the checks that
keep a device to one VM and away from what the host uses itself, also for a
snapshot revert; clones get none, and a VM with any is not migrated."""

from unittest.mock import MagicMock, patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import etree, html

from vrtManager.util import OperationError


from vrtManager.tests.fakes import by_model, domain
from vrtManager.tests.fakes import IOMMU_NODES, NODES, node


class HostUsbViewTests(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="hd", hostname="192.0.2.31", login="root", password="", type=1)
        self.instance = Instance.objects.create(compute=self.compute, name="kiosk-1", uuid="00000000-0000-4000-8000-0000000000e1")
        self.client.force_login(get_user_model().objects.create_superuser("hd", "hd@example.com", "pw"))
        patcher = patch("instances.models.wvmInstance")
        self.proxy = patcher.start().return_value
        self.addCleanup(patcher.stop)
        # the host of the node device fixture; another VM holds tablet 1/3 by address
        other = MagicMock(**{"name.return_value": "db-1", "isPersistent.return_value": False,
                             "XMLDesc.return_value": domain(by_model("<address bus='1' device='3'/>"))})
        self.proxy.wvm.listAllDevices.return_value = [node(*n) for n in NODES]
        self.proxy.domain_trees.side_effect = lambda: [("db-1", [etree.fromstring(other.XMLDesc())])]
        self.proxy.get_hostdevs.return_value = ([], [], [])

    def test_the_form_offers_what_can_be_given_and_says_why_not(self):
        page = html.fromstring(self.client.get(reverse("instances:host_devices", args=[self.instance.id])).content)
        options = {o.get("value"): (o.get("disabled") is not None, o.text_content()) for o in page.xpath("//select[@name='usb_device']/option[@value!='']")}
        self.assertEqual(sorted(options), ["1/1", "1/2", "1/3"])
        self.assertTrue(options["1/1"][0] and "is a hub" in options["1/1"][1])
        self.assertTrue(options["1/3"][0] and "is given to db-1" in options["1/3"][1])
        self.assertFalse(options["1/2"][0])
        # a device the VM has already
        self.proxy.domain_trees.side_effect = lambda: [("kiosk-1", [etree.fromstring(domain(by_model("<address bus='1' device='2'/>")))])]
        page = html.fromstring(self.client.get(reverse("instances:host_devices", args=[self.instance.id])).content)
        self.assertEqual(page.xpath("//option[@value='1/2']/@disabled"), ["disabled"])

    def test_a_device_is_given_by_address_when_the_host_has_several_of_its_model(self):
        url = reverse("instances:add_usb_hostdev", args=[self.instance.id])
        response = self.client.post(url, {"usb_device": "1/2"})
        self.assertEqual(response.status_code, 302)
        self.proxy.add_usb_hostdev.assert_called_once_with("0x0627", "0x0001", (1, 2))
        # refused on the server too: another VM's device, a hub
        for chosen, why in (("1/3", "is given to db-1"), ("1/1", "is a hub"), ("9/9", "has no USB device")):
            response = self.client.post(url, {"usb_device": chosen})
            with self.subTest(chosen=chosen):
                self.assertIn(why, " ".join(str(m) for m in get_messages(response.wsgi_request)))
        self.assertEqual(self.proxy.add_usb_hostdev.call_count, 1)

    def test_a_device_is_given_by_model_when_the_host_has_one_of_it(self):
        self.proxy.wvm.listAllDevices.return_value = [node(*n) for n in NODES if n[0] not in ("usb_1_2", "usb_1_2_1_0")]
        self.client.post(reverse("instances:add_usb_hostdev", args=[self.instance.id]), {"usb_device": "1/2"})
        self.proxy.add_usb_hostdev.assert_called_once_with("0x0627", "0x0001", None)

    def test_a_pci_device_is_given_when_it_can_be(self):
        url = reverse("instances:add_pci_hostdev", args=[self.instance.id])
        # the host's own NIC: refused with the reason
        response = self.client.post(url, {"pci_device": "0000:00:06.0"})
        self.assertIn("holds the host's eth0", " ".join(str(m) for m in get_messages(response.wsgi_request)))
        self.proxy.add_pci_hostdev.assert_not_called()
        self.client.post(url, {"pci_device": "0000:00:0a.0"})  # bound to vfio-pci, alone in its group
        self.proxy.add_pci_hostdev.assert_called_once_with("0000:00:0a.0")
        self.client.post(reverse("instances:delete_pci_hostdev", args=[self.instance.id]), {"address": "0000:00:0a.0"})
        self.proxy.delete_pci_hostdev.assert_called_once_with("0000:00:0a.0")

    def test_the_pci_form_waits_for_a_vm_that_runs_or_is_shut_off(self):
        url = reverse("instances:host_devices", args=[self.instance.id])
        for state, saved, frozen in ((libvirt.VIR_DOMAIN_RUNNING, 0, False), (libvirt.VIR_DOMAIN_SHUTOFF, 0, False),
                                     (libvirt.VIR_DOMAIN_PAUSED, 0, True), (libvirt.VIR_DOMAIN_SHUTOFF, 1, True)):
            self.proxy.instance.info.return_value = [state]
            self.proxy.instance.hasManagedSaveImage.return_value = saved
            page = html.fromstring(self.client.get(url).content)
            with self.subTest(state=state, saved=saved):
                self.assertEqual(page.xpath("//select[@name='pci_device']/@disabled"), ["disabled"] if frozen else [])

    def test_a_removal_is_logged_as_done_or_as_requested(self):
        from logs.models import Logs

        url = reverse("instances:delete_pci_hostdev", args=[self.instance.id])
        self.proxy.delete_pci_hostdev.return_value = False
        self.client.post(url, {"address": "0000:00:0a.0"})
        self.proxy.delete_pci_hostdev.return_value = True  # the guest has not let it go yet
        response = self.client.post(url, {"address": "0000:00:0a.0"})
        self.assertIn("the guest has not let it go yet", " ".join(str(m) for m in get_messages(response.wsgi_request)))
        rows = list(Logs.objects.filter(instance="kiosk-1").order_by("id").values_list("message", flat=True))
        self.assertEqual(rows, ["VM kiosk-1: remove PCI device 0000:00:0a.0",
                                "VM kiosk-1: request the removal of PCI device 0000:00:0a.0"])

    def test_a_running_vm_is_given_a_device_alone_a_shut_off_one_with_its_group(self):

        # the next start has the GPU's audio function managed: it goes along when the VM starts, not at a hot plug
        self.proxy.wvm.listAllDevices.return_value = [node(name, etree.tostring(n)) for name, n in IOMMU_NODES.items()]
        self.proxy.domain_trees.side_effect = lambda: []
        self.proxy.get_hostdevs.return_value = ([], [{"address": "0000:00:0e.0", "now": False, "next": True, "managed": True}], [])
        url = reverse("instances:host_devices", args=[self.instance.id])
        for active, offered in ((False, True), (True, False)):
            self.proxy.instance.isActive.return_value = active
            page = html.fromstring(self.client.get(url).content)
            with self.subTest(active=active):
                self.assertEqual(page.xpath("//option[@value='0000:00:0d.0']/@disabled") == [], offered)

    def test_a_device_is_taken_back_by_its_selector(self):
        url = reverse("instances:delete_usb_hostdev", args=[self.instance.id])
        self.client.post(url, {"vendor": "0x0627", "product": "0x0001", "address": ""})
        self.client.post(url, {"vendor": "0x0627", "product": "0x0001", "address": "1/3"})
        self.assertEqual([c.args[0] for c in self.proxy.delete_usb_hostdev.call_args_list],
                         [("0x0627", "0x0001", None), ("0x0627", "0x0001", (1, 3))])

    def test_only_superusers(self):
        self.client.force_login(get_user_model().objects.create_user("hd-user", "u@example.com", "pw"))
        self.assertEqual(self.client.get(reverse("instances:host_devices", args=[self.instance.id])).status_code, 403)
        self.client.post(reverse("instances:add_usb_hostdev", args=[self.instance.id]), {"usb_device": "1/2"})
        self.client.post(reverse("instances:add_pci_hostdev", args=[self.instance.id]), {"pci_device": "0000:00:0a.0"})
        self.client.post(reverse("instances:delete_pci_hostdev", args=[self.instance.id]), {"address": "0000:00:0a.0"})
        self.proxy.add_usb_hostdev.assert_not_called()
        self.proxy.add_pci_hostdev.assert_not_called()
        self.proxy.delete_pci_hostdev.assert_not_called()


class RevertTests(TestCase):
    """A revert gives the VM the host devices of the snapshot, as it ran and
    as saved: not one another VM names; and it holds the compute meanwhile."""

    def setUp(self):
        from instances.jobs import RevertSnapshot

        self.kind = RevertSnapshot()
        compute = Compute.objects.create(name="rv", hostname="192.0.2.32", login="root", password="", type=1)
        self.instance = Instance.objects.create(compute=compute, name="kiosk-1", uuid="00000000-0000-4000-8000-0000000000e2")
        patcher = patch("instances.jobs.wvmInstance")
        self.proxy = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.proxy.instance.name.return_value = "kiosk-1"
        self.proxy.wvm.listAllDevices.return_value = [node(*n) for n in NODES]
        self.proxy.domain_trees.side_effect = lambda: [("db-1", [etree.fromstring(domain(by_model("<address bus='1' device='3'/>")))])]
        self.params = {"instance": self.instance.id, "name": "s1", "external": False}

    def snapshot(self, running, saved=None):
        saved = f"<inactiveDomain><devices>{saved}</devices></inactiveDomain>" if saved is not None else ""
        self.proxy._snapshot.return_value.getXMLDesc.return_value = \
            f"<domainsnapshot><domain><devices>{running}</devices></domain>{saved}</domainsnapshot>"

    def precheck(self):
        op = MagicMock(params=self.params, intent={"compute": self.instance.compute_id}, user=MagicMock(is_superuser=True))
        with patch("instances.jobs._authorized", return_value=self.instance):
            self.kind.precheck(op, None)

    def test_a_device_another_vm_names_is_not_given_back(self):
        for running, saved in ((by_model(), None), ("", by_model())):  # the saved definition counts too
            self.snapshot(running, saved)
            with self.subTest(saved=saved), self.assertRaisesRegex(OperationError, "is given to db-1"):
                self.precheck()

    def test_the_compute_is_held_only_for_a_revert_with_host_devices(self):
        compute = f"compute:{self.instance.compute_id}"
        self.snapshot(by_model())
        self.assertEqual(self.kind.plan(MagicMock(is_superuser=True), self.params).claims[compute], "exclusive")
        self.snapshot("")
        self.assertEqual(self.kind.plan(MagicMock(is_superuser=True), self.params).claims[compute], "shared")
        self.precheck()  # no host device: the host's devices are not read
        self.proxy.wvm.listAllDevices.assert_not_called()
