"""Live tests that need a running guest OS with qemu-guest-agent.

Set TEST_LIBVIRT_GUEST_IMAGE to the path of an installed Linux image on the
test host: a BIOS-bootable qcow2 volume in a storage pool other than wvc-test,
with qemu-guest-agent enabled.
The tests boot wvc-test VMs from qcow2 overlays in the test pool, so the
image itself is only read. They are skipped while a running VM uses the
image, since its content would change under the overlays. Runs only with TEST_LIBVIRT_HOST set as well (see
instances/tests/livetest.py).
"""

import json
import os
import time
import unittest

import libvirt
import libvirt_qemu
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from lxml import etree
from vrtManager.connection import connection_manager

from operations.models import Operation

from . import livetest
from .test_create_instance import run
from instances.models import Instance
from instances.utils import refr

P = livetest.PREFIX
BOOT_TIMEOUT = 300


def wait_for(check, timeout, interval=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(interval)
    return check()


class LiveGuestTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = os.environ.get("TEST_LIBVIRT_GUEST_IMAGE")
        if not livetest.enabled() or not cls.image:
            raise unittest.SkipTest("Set TEST_LIBVIRT_HOST and TEST_LIBVIRT_GUEST_IMAGE to run the guest tests")
        cls.compute_args = dict(
            hostname=os.environ["TEST_LIBVIRT_HOST"],
            login=os.environ.get("TEST_LIBVIRT_LOGIN", ""),
            password=os.environ.get("TEST_LIBVIRT_PASSWORD", ""),
            type=int(os.environ.get("TEST_LIBVIRT_TYPE", 4)),
        )
        cls.conn = connection_manager.get_connection(*cls.compute_args.values())
        try:
            image = cls.conn.storageVolLookupByPath(cls.image)
        except libvirt.libvirtError as err:
            raise RuntimeError(f"TEST_LIBVIRT_GUEST_IMAGE must be a volume in a storage pool: {err}") from err
        if image.storagePoolLookupByVolume().name() == livetest.POOL:
            raise RuntimeError(f"TEST_LIBVIRT_GUEST_IMAGE must not be in the {livetest.POOL} pool, which the tests empty")
        cls.image_bytes = image.info()[1]  # overlays get the image's exact virtual size
        for dom in cls.conn.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE):
            if cls.image in dom.XMLDesc(0):
                raise unittest.SkipTest(f"{dom.name()} is running from {cls.image}")
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
        self.compute = Compute.objects.create(name="live-guest", details="test", **self.compute_args)
        admin = get_user_model().objects.create_superuser("guest_admin", "g@example.com", "pw")
        self.client.force_login(admin)
        self.client.raise_request_exception = False

    def tearDown(self):
        livetest.cleanup(self.conn)

    def boot(self, name, data_disk=False):
        """A running copy of the guest image; returns the domain and its Instance."""
        dom, _ = self.define(name, data_disk)
        return self.start(dom)

    def define(self, name, data_disk=False):
        """A stopped copy of the guest image; returns the domain and its Instance."""
        pool = self.conn.storagePoolLookupByName(livetest.POOL)
        root = pool.createXML(
            f"<volume><name>{P}{name}.qcow2</name><capacity unit='bytes'>{self.image_bytes}</capacity>"
            "<target><format type='qcow2'/></target>"
            f"<backingStore><path>{self.image}</path><format type='qcow2'/></backingStore></volume>",
            0,
        ).path()
        data = livetest.create_volume(self.conn, P + name + "-data") if data_disk else None
        disks = f"<disk type='file' device='disk'><driver name='qemu' type='qcow2'/><source file='{root}'/>" \
                "<target dev='vda' bus='virtio'/><serial>wvc-root</serial></disk>"
        if data:
            disks += f"<disk type='file' device='disk'><driver name='qemu' type='qcow2'/><source file='{data}'/>" \
                     "<target dev='vdb' bus='virtio'/><serial>wvc-data</serial></disk>"
        # No PCI controllers: libvirt then adds the root ports the devices need
        # plus one free port, which the NIC hotplug test uses. With explicit
        # controllers it adds no free port.
        dom = self.conn.defineXML(f"""
<domain type='kvm'>
  <name>{P}{name}</name>
  <memory unit='MiB'>2048</memory>
  <vcpu placement='static' current='1'>2</vcpu>
  <vcpus>
    <vcpu id='0' enabled='yes' hotpluggable='no' order='1'/>
    <vcpu id='1' enabled='no' hotpluggable='yes'/>
  </vcpus>
  <os><type arch='x86_64' machine='q35'>hvm</type><boot dev='hd'/></os>
  <features><acpi/><apic/></features>
  <cpu mode='host-model'/>
  <devices>
    {disks}
    <interface type='network'><source network='default'/><model type='virtio'/></interface>
    <channel type='unix'><target type='virtio' name='org.qemu.guest_agent.0'/></channel>
    <serial type='pty'/>
  </devices>
</domain>""")
        refr(self.compute)
        return dom, Instance.objects.get(compute=self.compute, uuid=dom.UUIDString())

    def start(self, dom):
        if not dom.isActive():
            dom.create()
        self.wait_agent(dom)
        return dom, Instance.objects.get(compute=self.compute, uuid=dom.UUIDString())

    def wait_agent(self, dom):
        self.assertTrue(wait_for(lambda: self.agent(dom, "guest-ping") is not None, BOOT_TIMEOUT), "guest agent never answered")

    def agent(self, dom, command):
        try:
            return json.loads(libvirt_qemu.qemuAgentCommand(dom, json.dumps({"execute": command}), 5, 0))["return"]
        except libvirt.libvirtError:
            return None

    def guest_view(self, dom):
        """Hardware as the guest agent reports it."""
        blocks = self.agent(dom, "guest-get-memory-blocks") or []
        block_size = (self.agent(dom, "guest-get-memory-block-info") or {}).get("size", 0)
        disks = sorted(
            # SATA disks report their serial as QEMU_HARDDISK_<serial>
            ((d["address"].get("serial") or "").removeprefix("QEMU_HARDDISK_"), d["address"]["bus-type"])
            for d in self.agent(dom, "guest-get-disks") or []
            if not d["partition"] and "address" in d
        )
        # Emulated NICs have QEMU's 52:54: prefix; guest-made interfaces (docker0,
        # veth) do not, and a bridge repeats its member's MAC.
        macs = {
            i["hardware-address"]
            for i in self.agent(dom, "guest-network-get-interfaces") or []
            if i.get("hardware-address", "").startswith("52:54:")
        }
        return {
            "vcpus": sum(1 for cpu in self.agent(dom, "guest-get-vcpus") or [] if cpu["online"]),
            "memory_mib": block_size * sum(1 for b in blocks if b["online"]) >> 20,
            "disks": disks,
            "macs": macs,
        }

    def config_view(self, dom):
        """The same hardware in the persistent definition."""
        tree = etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
        vcpu = tree.find("vcpu")
        return {
            "vcpus": int(vcpu.get("current", vcpu.text)),
            "memory_mib": int(tree.findtext("memory")) >> 10,
            "disks": sorted(
                (d.findtext("serial") or "", d.find("target").get("bus")) for d in tree.xpath("devices/disk[@device='disk']")
            ),
            "macs": set(tree.xpath("devices/interface/mac/@address")),
        }

    def assert_guest_matches_config(self, dom, timeout=60):
        """The guest sees what the persistent definition says (hotplugged devices may take a moment)."""
        wait_for(lambda: self.guest_view(dom) == self.config_view(dom), timeout)
        self.assertEqual(self.guest_view(dom), self.config_view(dom))

    def post(self, view, instance, data=None):
        response = self.client.post(
            reverse(f"instances:{view}", args=[instance.id]),
            data or {},
            HTTP_REFERER=reverse("instances:instance", args=[instance.id]),
        )
        self.assertEqual(response.status_code, 302, f"{view} failed")
        return response

    def live(self, dom):
        return etree.fromstring(dom.XMLDesc(0))

    def test_deleting_a_disk_the_guest_releases_deletes_the_volume(self):
        dom, inst = self.boot("gdel", data_disk=True)
        data = self.live(dom).xpath("devices/disk[target/@dev='vdb']/source/@file")[0]

        response = self.post("delete_vol", inst, {"dev": "vdb"})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.live(dom).xpath("devices/disk[target/@dev='vdb']"), "still attached")
        self.assertFalse(
            etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)).xpath("devices/disk[target/@dev='vdb']")
        )
        self.assertFalse(livetest.volume_exists(self.conn, data), "volume kept although the guest released it")

    def test_detaching_a_disk_removes_it_from_the_running_guest(self):
        dom, inst = self.boot("gdet", data_disk=True)
        data = self.live(dom).xpath("devices/disk[target/@dev='vdb']/source/@file")[0]

        response = self.post("detach_vol", inst, {"dev": "vdb"})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(wait_for(lambda: not self.live(dom).xpath("devices/disk[target/@dev='vdb']"), 30))
        self.assertTrue(livetest.volume_exists(self.conn, data), "detach must keep the volume")

    def test_nic_hotplug_and_unplug(self):
        dom, inst = self.boot("gnic")
        mac = "52:54:00:aa:03:01"

        self.post("add_network", inst, {"add-net-mac": mac, "add-net-network": "net:default", "add-net-model": "virtio"})
        self.assertTrue(self.live(dom).xpath("devices/interface[mac/@address=$m]", m=mac), "NIC not attached")
        self.assertTrue(
            wait_for(lambda: any(i["hardware-address"] == mac for i in self.agent(dom, "guest-network-get-interfaces") or []), 60),
            "guest does not see the new NIC",
        )

        self.post("delete_network", inst, {"delete_network": mac})
        self.assertTrue(wait_for(lambda: not self.live(dom).xpath("devices/interface[mac/@address=$m]", m=mac), 30))
        self.assertFalse(
            etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)).xpath("devices/interface[mac/@address=$m]", m=mac)
        )

    def test_vcpu_hotplug_reaches_the_guest(self):
        dom, inst = self.boot("gcpu")

        def online():
            return sum(1 for cpu in self.agent(dom, "guest-get-vcpus") or [] if cpu["online"])

        self.assertEqual(online(), 1)
        self.post("set_vcpu", inst, {"id": "1", "set_vcpu": "True"})
        self.assertTrue(wait_for(lambda: online() == 2, 60), "guest did not bring the new vCPU online")
        # the next start keeps it
        persistent = etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
        self.assertEqual(persistent.xpath("vcpus/vcpu[@id='1']/@enabled"), ["yes"])

    def test_agent_reports_the_guest_os_and_nic(self):
        dom, inst = self.boot("gagent")

        response = self.client.get(reverse("instances:osinfo", args=[inst.id]))
        self.assertEqual(response.status_code, 200)
        # One field from each agent call osinfo() merges: osinfo, timezone, host name
        self.assertLessEqual({"kernel-release", "zone", "host-name"}, set(response.json()))

        # The NIC is matched by MAC in the agent's report. Whether the guest has
        # an address depends on its network configuration, not on WebVirtCloud.
        mac = self.live(dom).xpath("devices/interface/mac/@address")[0]
        proxy = inst.proxy
        proxy.refresh_interface_addresses()
        self.assertIn(mac, [nic["hwaddr"] for nic in proxy._ip_cache["qemuga"].values()])

    def test_poweroff_shuts_the_guest_down(self):
        dom, inst = self.boot("goff")

        # A guest that is still booting ignores or delays the request (seen:
        # 20 s to over 3 min right after the agent came up). Let the boot
        # finish, then press power off again if needed, as a user would.
        time.sleep(60)
        for _ in range(6):
            self.assertEqual(self.post("poweroff", inst).status_code, 302)
            if wait_for(lambda: not dom.isActive(), 30):
                break
        self.assertFalse(dom.isActive(), "guest did not shut down on ACPI")

    # The guest sees the hardware WebVirtCloud configures

    def test_guest_sees_the_configured_hardware(self):
        dom, _ = self.boot("ghw", data_disk=True)

        self.assert_guest_matches_config(dom)

    def test_cpu_and_memory_resize_reach_the_guest_after_a_restart(self):
        dom, inst = self.boot("gres")

        self.post("force_off", inst)
        self.assertFalse(dom.isActive(), "force off left the VM running")
        self.post("resizevm_cpu", inst, {"vcpu": "2", "cur_vcpu": "2"})
        self.post("resize_memory", inst, {"memory": "3072", "cur_memory": "3072"})
        self.post("poweron", inst)
        self.wait_agent(dom)

        self.assert_guest_matches_config(dom)
        self.assertEqual(self.guest_view(dom)["vcpus"], 2)
        self.assertEqual(self.guest_view(dom)["memory_mib"], 3072)

    def test_disk_changes_reach_the_guest(self):
        dom, inst = self.boot("gdisk", data_disk=True)
        data = self.live(dom).xpath("devices/disk[target/@dev='vdb']/source/@file")[0]

        # Hotplugged at once
        self.post("add_new_vol", inst, {"storage": livetest.POOL, "name": P + "gdisk-new", "size": "1", "format": "qcow2", "bus": "virtio"})
        self.assertEqual(len(self.config_view(dom)["disks"]), 3, "disk was not added")
        self.assert_guest_matches_config(dom)

        # Persistent only: bus and serial change at the next start
        self.post("edit_volume", inst, {
            "edit_volume": "1", "dev": "vdb", "vol_path": data, "vol_bus": "sata",
            "vol_serial": "wvc-edited", "vol_format": "qcow2",
        })
        self.assertNotIn(("wvc-edited", "sata"), self.guest_view(dom)["disks"])
        self.post("powercycle", inst)
        self.wait_agent(dom)

        self.assert_guest_matches_config(dom)
        self.assertIn(("wvc-edited", "sata"), self.guest_view(dom)["disks"])

    def test_nic_mac_change_reaches_the_guest_after_a_restart(self):
        dom, inst = self.boot("gmac")
        old, new = self.live(dom).xpath("devices/interface/mac/@address")[0], "52:54:00:aa:05:01"

        self.post("change_network", inst, {
            "net-old-mac-0": old, "net-mac-0": new, "net-source-0": "net:default",
            "net-model-0": "virtio", "net-nwfilter-0": "",
        })
        self.assertEqual(self.guest_view(dom)["macs"], {old})  # pending until the next start
        self.post("powercycle", inst)
        self.wait_agent(dom)

        self.assert_guest_matches_config(dom)
        self.assertEqual(self.guest_view(dom)["macs"], {new})

    def test_clone_guest_sees_its_own_nic_and_disk(self):
        source, inst = self.define("gsrc")
        mac = "52:54:00:aa:06:01"

        self.post("clone", inst, {"name": P + "gclone", "disk-vda": P + "gclone.qcow2", "clone-net-mac-0": mac,
                                   "submission_key": "key-gclone"})
        run(Operation.objects.get(kind="instance.clone"))
        clone = self.conn.lookupByName(P + "gclone")
        self.start(clone)

        self.assert_guest_matches_config(clone)
        self.assertEqual(self.guest_view(clone)["macs"], {mac})
        self.assertNotIn(
            source.XMLDesc(0).split("<source file='")[1].split("'")[0],
            clone.XMLDesc(0),
            "the clone uses the source's disk",
        )

    # Power and state operations seen from the guest

    def test_snapshot_revert_restores_the_running_guest(self):
        dom, inst = self.boot("gsnap")
        mac = "52:54:00:aa:07:01"

        inst.proxy.create_snapshot("before")
        self.assertEqual(dom.snapshotNum(0), 1, "snapshot was not taken")
        self.post("add_network", inst, {"add-net-mac": mac, "add-net-network": "net:default", "add-net-model": "virtio"})
        self.assertTrue(wait_for(lambda: mac in self.guest_view(dom)["macs"], 60), "guest does not see the new NIC")

        inst.proxy.snapshot_revert("before")
        self.wait_agent(dom)

        self.assertTrue(dom.isActive(), "reverting a running snapshot left the VM stopped")
        self.assertNotIn(mac, self.config_view(dom)["macs"])
        self.assert_guest_matches_config(dom)

    def test_suspend_and_resume(self):
        dom, inst = self.boot("gsus")

        self.post("suspend", inst)
        self.assertEqual(dom.state()[0], libvirt.VIR_DOMAIN_PAUSED)
        self.assertIsNone(self.agent(dom, "guest-ping"), "a paused guest answered")

        self.post("resume", inst)
        self.assertEqual(dom.state()[0], libvirt.VIR_DOMAIN_RUNNING)
        self.wait_agent(dom)
        self.assert_guest_matches_config(dom)

    def test_a_paused_guest_gets_its_new_memory_once_resumed(self):
        dom, inst = self.boot("gmem")

        def balloon_mib():
            return dom.memoryStats().get("actual", 0) >> 10

        def config_mib(tag):
            return int(etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)).findtext(tag)) >> 10

        for cur in (1536, 2048):  # down, then back up to the maximum
            self.post("suspend", inst)
            # the posted maximum is ignored: an active VM keeps its own
            self.post("resize_memory", inst, {"memory": "4096", "cur_memory": str(cur)})
            self.assertEqual(dom.state()[0], libvirt.VIR_DOMAIN_PAUSED)
            self.assertEqual((config_mib("currentMemory"), config_mib("memory")), (cur, 2048))
            self.post("resume", inst)
            self.assertTrue(wait_for(lambda: balloon_mib() == cur, 60), f"balloon at {balloon_mib()} MiB, not {cur}")
            self.wait_agent(dom)
