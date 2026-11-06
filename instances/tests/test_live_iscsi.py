"""Live check that a LUN of an iSCSI pool attaches to a VM.

An iSCSI volume's path is a /dev/disk/by-path link, not the pool target
plus the volume name, and the pool knows no format: the LUN attaches as
<disk type='block'> with a raw driver. Runs only with TEST_LIBVIRT_HOST
and TEST_LIBVIRT_ISCSI_TARGET (the IQN of a target with at least one LUN
on 127.0.0.1 of that host, open to any initiator: the Vagrant computes
serve one) set.
"""

import os
import unittest

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from lxml import etree
from vrtManager.connection import connection_manager

from vrtManager.tests import livetest
from instances.models import Instance
from instances.utils import refr

P = livetest.PREFIX
POOL = P + "iscsi"
# a running q35 VM hotplugs the disk into a free root port; the USB
# controller and the balloon take two
PCI = "<controller type='pci' index='0' model='pcie-root'/>" + "<controller type='pci' model='pcie-root-port'/>" * 3


class LiveIscsiTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        if not (livetest.enabled() and os.environ.get("TEST_LIBVIRT_ISCSI_TARGET")):
            raise unittest.SkipTest("Set TEST_LIBVIRT_HOST and TEST_LIBVIRT_ISCSI_TARGET to run the iSCSI tests")
        cls.compute_args = dict(
            hostname=os.environ["TEST_LIBVIRT_HOST"],
            login=os.environ.get("TEST_LIBVIRT_LOGIN", ""),
            password=os.environ.get("TEST_LIBVIRT_PASSWORD", ""),
            type=int(os.environ.get("TEST_LIBVIRT_TYPE", 4)),
        )
        cls.conn = connection_manager.get_connection(*cls.compute_args.values())
        livetest.cleanup(cls.conn)
        cls.inventory = livetest.inventory(cls.conn)
        cls.pool = cls.conn.storagePoolCreateXML(
            f"<pool type='iscsi'><name>{POOL}</name><source><host name='127.0.0.1'/>"
            f"<device path='{os.environ['TEST_LIBVIRT_ISCSI_TARGET']}'/></source>"
            "<target><path>/dev/disk/by-path</path></target></pool>",
            0,
        )
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        try:
            livetest.cleanup(cls.conn)
            cls.pool.destroy()  # transient: gone once stopped
        finally:
            super().tearDownClass()
        if livetest.inventory(cls.conn) != cls.inventory:
            raise AssertionError("Live tests changed objects outside the test namespace")

    def setUp(self):
        self.compute = Compute.objects.create(name="live-iscsi", details="test", **self.compute_args)
        admin = get_user_model().objects.create_superuser("live_admin", "l@example.com", "pw")
        self.client.force_login(admin)

    def tearDown(self):
        livetest.cleanup(self.conn)

    def disks(self, dom, flags=0):
        return [
            (d.get("type"), d.find("driver").get("type"), d.find("source").get("dev"), d.find("target").get("dev"))
            for d in etree.fromstring(dom.XMLDesc(flags)).findall("devices/disk")
        ]

    def test_a_lun_attaches_as_a_block_disk(self):
        lun = self.pool.listAllVolumes()[0]
        for running in (False, True):
            with self.subTest(running=running):
                dom = self.conn.defineXML(
                    f"<domain type='kvm'><name>{P}iscsi-{int(running)}</name><memory unit='MiB'>128</memory>"
                    "<vcpu>1</vcpu><os><type arch='x86_64' machine='q35'>hvm</type></os><features><acpi/></features>"
                    f"<devices>{PCI}</devices></domain>"
                )
                refr(self.compute)
                inst = Instance.objects.get(compute=self.compute, uuid=dom.UUIDString())
                if running:
                    dom.create()

                self.client.post(
                    reverse("instances:add_existing_vol", args=[inst.id]),
                    {"selected_storage": POOL, "vols": lun.name(), "bus": "virtio", "cache": "default"},
                    HTTP_REFERER=reverse("instances:instance", args=[inst.id]),
                )

                expected = [("block", "raw", lun.path(), "vda")]
                self.assertEqual(self.disks(dom, libvirt.VIR_DOMAIN_XML_INACTIVE), expected)
                self.assertEqual(self.disks(dom), expected)
                if running:
                    self.assertEqual(dom.blockInfo("vda")[0], lun.info()[1])  # what the guest sees
                livetest.cleanup(self.conn)
