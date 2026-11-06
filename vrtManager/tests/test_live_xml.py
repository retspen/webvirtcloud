"""Live checks that persistent edits keep secrets and pending changes.

Every edit that redefines the domain must start from the persistent
definition with secrets (VIR_DOMAIN_XML_INACTIVE | VIR_DOMAIN_XML_SECURE).
Runs only with TEST_LIBVIRT_HOST set (see vrtManager/tests/livetest.py).
"""

import os
import unittest

import libvirt
from django.test import SimpleTestCase
from lxml import etree
from vrtManager.connection import connection_manager
from vrtManager.instance import wvmInstance

from vrtManager.tests import livetest

P = livetest.PREFIX
MAC = "52:54:00:aa:01:01"
DEVICES = (
    f"<interface type='network'><mac address='{MAC}'/><source network='default'/><model type='virtio'/></interface>"
    "<graphics type='vnc' autoport='yes' passwd='keep1234'/>"
    "<video><model type='vga' primary='yes'/></video>"
)
PERSISTENT = libvirt.VIR_DOMAIN_XML_INACTIVE | libvirt.VIR_DOMAIN_XML_SECURE

# name -> (edit, allowed while running)
EDITS = {
    "set_bootmenu": (lambda vm: vm.set_bootmenu(1), True),
    "set_bootorder": (lambda vm: vm.set_bootorder({0: {"type": "disk", "dev": "vda"}}), True),
    "set_vcpu_hotplug": (lambda vm: vm.set_vcpu_hotplug(True, 1), False),
    "set_console_keymap": (lambda vm: vm.set_console_keymap("de"), True),
    "set_console_listener_addr": (lambda vm: vm.set_console_listener_addr("127.0.0.1"), True),
    "set_video_model": (lambda vm: vm.set_video_model("virtio"), True),
    "resize_cpu": (lambda vm: vm.resize_cpu("1", "2"), True),
    "resize_mem": (lambda vm: vm.resize_mem(128, 160), False),
    "resize_disk": (lambda vm: vm.resize_disk([{"path": vm.get_disk_devices()[0]["path"], "size_new": 96 << 20}]), True),
    "set_options": (lambda vm: vm.set_options({"title": "edited"}), True),
    "set_qos": (lambda vm: vm.set_qos(MAC, "inbound", 100, 200, 300), True),
    "unset_qos": (lambda vm: vm.unset_qos(MAC, "inbound"), True),
}


class LivePersistentEditTestCase(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        if not livetest.enabled():
            raise unittest.SkipTest("Set TEST_LIBVIRT_HOST to run the live libvirt tests")
        cls.args = (
            os.environ["TEST_LIBVIRT_HOST"],
            os.environ.get("TEST_LIBVIRT_LOGIN", ""),
            os.environ.get("TEST_LIBVIRT_PASSWORD", ""),
            int(os.environ.get("TEST_LIBVIRT_TYPE", 4)),
        )
        cls.conn = connection_manager.get_connection(*cls.args)
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

    def tearDown(self):
        livetest.cleanup(self.conn)

    def vm(self, name):
        disk = livetest.create_volume(self.conn, P + name)
        dom = livetest.define_vm(self.conn, P + name, [disk], extra_devices=DEVICES)
        return dom, wvmInstance(*self.args, None, uuid=dom.UUIDString())

    def persistent(self, dom):
        return etree.fromstring(dom.XMLDesc(PERSISTENT))

    def test_edits_of_a_stopped_vm_keep_the_vnc_password(self):
        for name, (edit, _) in EDITS.items():
            with self.subTest(name):
                try:
                    dom, vm = self.vm("xml-stopped")
                    edit(vm)
                    self.assertEqual(self.persistent(dom).xpath("string(devices/graphics/@passwd)"), "keep1234")
                finally:
                    livetest.cleanup(self.conn)

    def test_edits_of_a_running_vm_keep_pending_changes(self):
        for name, (edit, while_running) in EDITS.items():
            if not while_running:
                continue
            with self.subTest(name):
                try:
                    dom, vm = self.vm("xml-running")
                    dom.create()
                    # A pending change: only the persistent definition has 192 MiB.
                    tree = self.persistent(dom)
                    tree.find("memory").text = str(192 * 1024)
                    tree.find("currentMemory").text = str(192 * 1024)
                    self.conn.defineXML(etree.tostring(tree).decode())

                    edit(vm)

                    after = self.persistent(dom)
                    self.assertEqual(after.findtext("memory"), str(192 * 1024), "pending memory change lost")
                    self.assertEqual(after.xpath("string(devices/graphics/@passwd)"), "keep1234")
                finally:
                    livetest.cleanup(self.conn)
