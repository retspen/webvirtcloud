"""Live checks of VM disks on an LVM pool, created on the storage page.

Volumes of a logical pool are block devices: they attach as <disk
type='block'> with a raw driver. The pool cannot resize them, so a disk
resize is refused with a message. Runs only with TEST_LIBVIRT_HOST
and TEST_LIBVIRT_LVM_DEVICE set; the device, an empty disk of at least
4 GiB on that host, is wiped (the Vagrant computes' /dev/vdb).
"""

import os
import unittest

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from lxml import etree
from vrtManager.connection import connection_manager

from . import livetest
from instances.models import Instance
from instances.utils import refr

P = livetest.PREFIX
POOL = P + "lvm"
GIB = 1 << 30
# a running q35 VM hotplugs each disk into a free root port; the USB
# controller and the balloon take two
PCI = "<controller type='pci' index='0' model='pcie-root'/>" + "<controller type='pci' model='pcie-root-port'/>" * 4


class LiveLvmTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        if not (livetest.enabled() and os.environ.get("TEST_LIBVIRT_LVM_DEVICE")):
            raise unittest.SkipTest("Set TEST_LIBVIRT_HOST and TEST_LIBVIRT_LVM_DEVICE to run the LVM tests")
        cls.compute_args = dict(
            hostname=os.environ["TEST_LIBVIRT_HOST"],
            login=os.environ.get("TEST_LIBVIRT_LOGIN", ""),
            password=os.environ.get("TEST_LIBVIRT_PASSWORD", ""),
            type=int(os.environ.get("TEST_LIBVIRT_TYPE", 4)),
        )
        cls.conn = connection_manager.get_connection(*cls.compute_args.values())
        livetest.cleanup(cls.conn)
        cls.inventory = livetest.inventory(cls.conn)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        try:
            livetest.cleanup(cls.conn)
            try:
                pool = cls.conn.storagePoolLookupByName(POOL)
            except libvirt.libvirtError:
                pass
            else:
                for vol in pool.listAllVolumes():
                    vol.delete(0)
                pool.destroy()
                pool.delete(0)  # removes the volume group
                pool.undefine()
        finally:
            super().tearDownClass()
        if livetest.inventory(cls.conn) != cls.inventory:
            raise AssertionError("Live tests changed objects outside the test namespace")

    def setUp(self):
        self.compute = Compute.objects.create(name="live-lvm", details="test", **self.compute_args)
        admin = get_user_model().objects.create_superuser("live_admin", "l@example.com", "pw")
        self.client.force_login(admin)
        self.pool = self.lvm_pool()

    def tearDown(self):
        self.clear()

    def clear(self):
        livetest.cleanup(self.conn)
        for vol in self.pool.listAllVolumes():
            vol.delete(0)

    def lvm_pool(self):
        try:
            return self.conn.storagePoolLookupByName(POOL)
        except libvirt.libvirtError:
            self.client.post(
                reverse("storages", args=[self.compute.id]),
                {"create": "", "name": POOL, "stg_type": "logical", "source": os.environ["TEST_LIBVIRT_LVM_DEVICE"],
                 "erase_device": "on"},
            )
        pool = self.conn.storagePoolLookupByName(POOL)
        self.assertTrue(pool.isActive())
        self.assertEqual(etree.fromstring(pool.XMLDesc(0)).findtext("target/path"), f"/dev/{POOL}")
        return pool

    def vm(self, name, disk=None):
        disks = (
            "<disk type='block' device='disk'><driver name='qemu' type='raw'/>"
            f"<source dev='{disk}'/><target dev='vda' bus='virtio'/></disk>"
            if disk
            else ""
        )
        dom = self.conn.defineXML(
            f"<domain type='kvm'><name>{P}{name}</name><memory unit='MiB'>128</memory><vcpu>1</vcpu>"
            "<os><type arch='x86_64' machine='q35'>hvm</type></os><features><acpi/></features>"
            f"<devices>{disks}{PCI}</devices></domain>"
        )
        refr(self.compute)
        return dom, Instance.objects.get(compute=self.compute, uuid=dom.UUIDString())

    def lv(self, name, gib=1):
        return self.pool.createXML(
            f"<volume><name>{P}{name}</name><capacity unit='GiB'>{gib}</capacity></volume>", 0
        ).path()

    def post(self, view, instance, data):
        return self.client.post(
            reverse(f"instances:{view}", args=[instance.id]),
            data,
            HTTP_REFERER=reverse("instances:instance", args=[instance.id]),
        )

    def disks(self, dom, flags=0):
        return {
            d.find("target").get("dev"): (
                d.get("type"), d.find("driver").get("type"), d.find("source").get("dev")
            )
            for d in etree.fromstring(dom.XMLDesc(flags)).findall("devices/disk")
        }

    def test_new_and_existing_volumes_attach_as_block_disks(self):
        for running in (False, True):
            with self.subTest(running=running):
                dom, inst = self.vm(f"attach-{int(running)}")
                if running:
                    dom.create()
                existing = self.lv(f"existing-{int(running)}")

                self.post("add_new_vol", inst, {"storage": POOL, "name": f"{P}new-{int(running)}",
                                                "size": "1", "format": "qcow2", "bus": "virtio", "cache": "default"})
                self.post("add_existing_vol", inst, {"selected_storage": POOL, "vols": f"{P}existing-{int(running)}",
                                                     "bus": "virtio", "cache": "default"})

                expected = {
                    "vda": ("block", "raw", f"/dev/{POOL}/{P}new-{int(running)}"),
                    "vdb": ("block", "raw", existing),
                }
                self.assertEqual(self.disks(dom, libvirt.VIR_DOMAIN_XML_INACTIVE), expected)
                self.assertEqual(self.disks(dom), expected)
                self.clear()

    def test_a_disk_resize_is_refused_with_a_message_and_changes_nothing(self):
        # libvirt's LVM pool cannot change a volume's capacity
        for state in ("stopped", "running", "paused"):
            with self.subTest(state=state):
                path = self.lv(f"resize-{state}")
                dom, inst = self.vm(f"resize-{state}", path)
                if state != "stopped":
                    dom.create()
                if state == "paused":
                    dom.suspend()

                response = self.post("resize_disk", inst, {"disk_size_vda": "2"})

                self.assertRedirects(response, reverse("instances:instance", args=[inst.id]) + "#resize",
                                     fetch_redirect_response=False)
                shown = [str(m) for m in get_messages(response.wsgi_request)]
                self.assertEqual(shown[-1], "The storage pool of vda cannot resize its volumes")
                self.assertNotIn("Disk is resized: vda", shown)
                self.assertEqual(self.conn.storageVolLookupByPath(path).info()[1], GIB)
                if state != "stopped":
                    self.assertEqual(dom.blockInfo("vda")[0], GIB)  # what the guest sees
                self.clear()
