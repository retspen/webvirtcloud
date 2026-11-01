"""Live checks of VM creation: the queued job defines the VM, and a failed
one leaves no volumes behind.

Runs only with TEST_LIBVIRT_HOST set (see instances/tests/livetest.py).
"""

import os
import unittest

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse
from lxml import etree
from vrtManager.connection import connection_manager

from operations.models import Operation
from operations.tests import fakes
from operations.worker import Worker

from . import livetest
from .test_live_jobs import wait_for

P = livetest.PREFIX


class LiveCreateTestCase(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        if not livetest.enabled():
            raise unittest.SkipTest("Set TEST_LIBVIRT_HOST to run the live libvirt tests")
        cls.compute_args = dict(
            hostname=os.environ["TEST_LIBVIRT_HOST"],
            login=os.environ.get("TEST_LIBVIRT_LOGIN", ""),
            password=os.environ.get("TEST_LIBVIRT_PASSWORD", ""),
            type=int(os.environ.get("TEST_LIBVIRT_TYPE", 4)),
        )
        cls.conn = connection_manager.get_connection(*cls.compute_args.values())
        livetest.cleanup(cls.conn)
        livetest.ensure_pool(cls.conn)
        cls.inventory = livetest.inventory(cls.conn)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        try:
            livetest.remove_pool(cls.conn)
        finally:
            super().tearDownClass()
        if livetest.inventory(cls.conn) != cls.inventory:
            raise AssertionError("Live tests changed objects outside the test namespace")

    def setUp(self):
        self.compute = Compute.objects.create(name="live-create", details="test", **self.compute_args)
        admin = get_user_model().objects.create_superuser("create_admin", "c@example.com", "pw")
        self.client.force_login(admin)
        self.client.raise_request_exception = False

    def tearDown(self):
        livetest.cleanup(self.conn)

    def create(self, name, **overrides):
        data = {
            "name": P + name,
            "firmware": "BIOS",
            "vcpu": 1,
            "vcpu_mode": "host-model",
            "memory": 128,
            "hdd_size": 1,
            "storage": livetest.POOL,
            "mac": "52:54:00:aa:03:01",
            "networks": "default",
            "nwfilter": "",
            "net_model": "virtio",
            "cache_mode": "none",
            "video": "vga",
            "listener_addr": "0.0.0.0",
            "add_cdrom": "None",
            "add_input": "None",
            "create": True,
            "submission_key": "key-" + name,
        }
        data.update(overrides)
        response = self.client.post(
            reverse("instances:create_instance", args=[self.compute.id, "x86_64", "q35"]), data
        )
        self.work()
        return response

    def work(self):
        """Run the queued jobs with an in-thread worker."""
        worker = Worker(concurrency=1, tick=0.1, heartbeat_every=1, progress_every=1, exit_on_lost_lease=False)
        thread = fakes.start_worker(worker)
        try:
            self.assertTrue(wait_for(lambda: not Operation.objects.filter(state__in=Operation.ACTIVE).exists(), 180))
        finally:
            fakes.stop_worker(worker, thread)

    def volumes(self):
        pool = self.conn.storagePoolLookupByName(livetest.POOL)
        pool.refresh(0)
        return set(pool.listVolumes())

    def domain_exists(self, name):
        try:
            self.conn.lookupByName(name)
            return True
        except libvirt.libvirtError:
            return False

    def assert_nothing_left(self, name, response):
        self.assertLess(response.status_code, 500)
        self.assertEqual(self.volumes(), set(), "a volume was left behind")
        self.assertFalse(self.domain_exists(P + name))

    def test_invalid_cache_mode_allocates_nothing(self):
        self.assert_nothing_left("cr-cache", self.create("cr-cache", cache_mode="bogus"))

    def test_a_firmware_the_host_does_not_offer_allocates_nothing(self):
        self.assert_nothing_left("cr-uefi", self.create("cr-uefi", firmware="Coreboot"))

    def test_rejected_definition_removes_the_new_disk(self):
        self.assert_nothing_left("cr-define", self.create("cr-define", video="no-such-model"))

    def test_successful_creation(self):
        response = self.create("cr-ok")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.domain_exists(P + "cr-ok"))
        self.assertEqual(len(self.volumes()), 1)

    def offered(self):
        page = self.client.get(reverse("instances:create_instance", args=[self.compute.id, "x86_64", "q35"]))
        return page.context["firmwares"], page.context["tpm_support"]

    def test_uefi_boots_without_secure_boot(self):
        self.assertIn("UEFI", self.offered()[0], "no UEFI offered for q35")

        self.create("cr-uefi-ok", firmware="UEFI")

        dom = self.conn.lookupByName(P + "cr-uefi-ok")
        dom.create()
        tree = etree.fromstring(dom.XMLDesc(0))
        self.assertEqual(tree.find("os").get("firmware"), "efi")
        self.assertNotEqual(tree.find("os/loader").get("secure"), "yes")
        self.assertTrue(tree.findtext("os/nvram"))

    def test_secure_boot_with_a_tpm_boots_as_windows_11_needs(self):
        firmwares, tpm_support = self.offered()
        if "UEFI Secure Boot" not in firmwares or not tpm_support:
            self.skipTest("the host offers no Secure Boot with Microsoft's keys, or no swtpm")

        self.create("cr-secboot", firmware="UEFI Secure Boot", tpm="true")

        dom = self.conn.lookupByName(P + "cr-secboot")
        dom.create()
        tree = etree.fromstring(dom.XMLDesc(0))
        self.assertEqual(tree.find("os/loader").get("secure"), "yes")
        self.assertEqual(tree.find("features/smm").get("state"), "on")
        # the variables libvirt chose come with Microsoft's keys enrolled
        self.assertEqual(tree.xpath("os/firmware/feature[@name='enrolled-keys']/@enabled"), ["yes"])
        self.assertEqual(tree.xpath("devices/tpm/backend/@version"), ["2.0"])

    def test_every_offered_cdrom_bus_creates_a_vm_that_starts(self):
        page = self.client.get(reverse("instances:create_instance", args=[self.compute.id, "x86_64", "q35"]))
        buses = page.context["cdrom_buses"]
        self.assertTrue(buses)
        for i, bus in enumerate(buses):
            with self.subTest(bus=bus):
                self.create(f"cr-cd-{bus}", add_cdrom=bus, mac=f"52:54:00:aa:03:1{i}")
                dom = self.conn.lookupByName(P + f"cr-cd-{bus}")
                self.assertEqual(etree.fromstring(dom.XMLDesc(0)).xpath("devices/disk[@device='cdrom']/target/@bus"), [bus])
                dom.create()
                self.assertTrue(dom.isActive())

    def test_input_device_keeps_the_machine_usb_controller(self):
        self.create("cr-input", add_input="usb")
        tree = etree.fromstring(self.conn.lookupByName(P + "cr-input").XMLDesc(0))
        self.assertEqual(tree.xpath("devices/controller[@type='usb']/@model"), ["qemu-xhci"])
        self.assertTrue(tree.xpath("devices/input[@type='tablet' and @bus='usb']"))

    def test_networks_without_a_mac_of_their_own(self):
        self.create("cr-macs", networks="default,default")
        macs = etree.fromstring(self.conn.lookupByName(P + "cr-macs").XMLDesc(0)).xpath("devices/interface/mac/@address")
        self.assertEqual(len(macs), 2)
        self.assertEqual(macs[0], "52:54:00:aa:03:01")

    def test_api_rejected_definition_removes_the_new_disk(self):
        response = self.client.post(
            f"/api/v1/computes/{self.compute.id}/instances/create/x86_64/q35/",
            {
                "name": P + "cr-api",
                "vcpu": 1,
                "vcpu_mode": "host-model",
                "memory": 128,
                "networks": "default",
                "mac": "52:54:00:aa:03:02",
                "nwfilter": "",
                "storage": livetest.POOL,
                "hdd_size": 1,
                "cache_mode": "none",
                "meta_prealloc": False,
                "virtio": True,
                "qemu_ga": False,
                "listener_addr": "0.0.0.0",
                "video": "no-such-model",
                "add_cdrom": "None",
                "add_input": "None",
                "submission_key": "key-cr-api",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 202, response.content)
        self.work()
        self.assertEqual(self.volumes(), set(), "a volume was left behind")
        self.assertFalse(self.domain_exists(P + "cr-api"))

