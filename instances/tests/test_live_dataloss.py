"""Live tests for cases that lost disks or changed the wrong VM.

Each test asserts the safe behavior. Known unfixed cases are marked
expectedFailure; a fix turns them into unexpected successes, which fail
the run until the marker is removed. Runs only with
TEST_LIBVIRT_HOST set (see instances/tests/livetest.py).
"""

import os
import unittest

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from vrtManager.connection import connection_manager

from . import livetest
from instances.models import Instance
from instances.utils import refr

P = livetest.PREFIX


class LiveDataLossTestCase(TestCase):
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
        # Last: a failure above must not leave the class transaction open,
        # which would lock the shared test database for later test classes.
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
        self.compute = Compute.objects.create(name="live-dataloss", details="test", **self.compute_args)
        admin = get_user_model().objects.create_superuser("live_admin", "l@example.com", "pw")
        self.client.force_login(admin)
        self.client.raise_request_exception = False

    def tearDown(self):
        livetest.cleanup(self.conn)

    # helpers

    def vm(self, name, disks, uefi=False, extra_devices=""):
        dom = livetest.define_vm(self.conn, P + name, disks, uefi=uefi, extra_devices=extra_devices)
        refr(self.compute)
        return dom, Instance.objects.get(compute=self.compute, uuid=dom.UUIDString())

    def post(self, view, instance, data=None):
        return self.client.post(
            reverse(f"instances:{view}", args=[instance.id]),
            data or {},
            HTTP_REFERER=reverse("instances:instance", args=[instance.id]),
        )

    def disk_sources(self, dom, flags=0):
        from lxml import etree

        return {
            d.find("target").get("dev"): d.find("source").get("file")
            for d in etree.fromstring(dom.XMLDesc(flags)).findall("devices/disk")
        }

    def domain_exists(self, uuid):
        try:
            self.conn.lookupByUUIDString(uuid)
            return True
        except libvirt.libvirtError:
            return False

    # External snapshots

    def test_revert_external_snapshot_keeps_disk_added_later(self):
        base = livetest.create_volume(self.conn, P + "r03-a")
        dom, inst = self.vm("r03-a", [base])
        inst.proxy.create_external_snapshot("snap")

        later = livetest.create_volume(self.conn, P + "r03-later")
        dom.attachDeviceFlags(
            f"<disk type='file' device='disk'><driver name='qemu' type='qcow2'/>"
            f"<source file='{later}'/><target dev='vdb' bus='virtio'/></disk>",
            libvirt.VIR_DOMAIN_AFFECT_CONFIG,
        )
        inst.proxy.revert_external_snapshot("snap")

        self.assertTrue(livetest.volume_exists(self.conn, later), "revert deleted a disk the snapshot never had")
        self.assertEqual(set(self.disk_sources(dom, libvirt.VIR_DOMAIN_XML_INACTIVE)), {"vda"})

    def test_delete_older_external_snapshot_keeps_newer_snapshot_files(self):
        base = livetest.create_volume(self.conn, P + "r03-b")
        dom, inst = self.vm("r03-b", [base])
        inst.proxy.create_external_snapshot("older")
        inst.proxy.create_external_snapshot("newer")
        sources = set(self.disk_sources(dom).values())

        inst.proxy.delete_external_snapshot("older")

        for path in sources:
            self.assertTrue(livetest.volume_exists(self.conn, path), f"{path} was deleted")
        self.assertIn("newer", dom.snapshotListNames(0))

    # Internal snapshots of UEFI VMs

    def _uefi_internal_snapshot(self, running):
        base = livetest.create_volume(self.conn, P + "r13")
        dom, inst = self.vm("r13", [base], uefi=True)
        if running:
            dom.create()
        os_before = self.os_xml(dom)

        # Taken where libvirt supports it, otherwise refused; never a
        # rewritten loader or NVRAM.
        try:
            inst.proxy.create_snapshot("snap")
        except libvirt.libvirtError:
            self.assertEqual(dom.snapshotNum(0), 0)
        self.assertEqual(self.os_xml(dom), os_before)

    def os_xml(self, dom):
        from lxml import etree

        return etree.tostring(etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)).find("os"))

    def test_uefi_internal_snapshot_of_a_stopped_vm(self):
        self._uefi_internal_snapshot(running=False)

    def test_uefi_internal_snapshot_of_a_running_vm(self):
        self._uefi_internal_snapshot(running=True)

    # Destroy

    def test_destroy_keeps_a_volume_another_vm_uses(self):
        shared = livetest.create_volume(self.conn, P + "r14-shared")
        _, inst = self.vm("r14-a", [shared])
        self.vm("r14-b", [shared])

        response = self.post("destroy", inst, {"delete_disk": "1"})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(livetest.volume_exists(self.conn, shared), "destroy deleted another VM's disk")

    def _destroy_base_of_another_vms_overlay(self, running):
        base = livetest.create_volume(self.conn, P + "r14-base")
        pool = self.conn.storagePoolLookupByName(livetest.POOL)
        overlay = pool.createXML(
            f"<volume><name>{P}r14-overlay.qcow2</name><capacity unit='MiB'>64</capacity>"
            f"<target><format type='qcow2'/></target><backingStore><path>{base}</path>"
            "<format type='qcow2'/></backingStore></volume>",
            0,
        ).path()
        _, inst = self.vm("r14-base", [base])
        dom_b, _ = self.vm("r14-overlay", [overlay])
        if running:
            dom_b.create()

        response = self.post("destroy", inst, {"delete_disk": "1"})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(livetest.volume_exists(self.conn, base), "deleted the backing file of another VM's disk")

    def test_destroy_keeps_the_backing_file_of_a_stopped_vm(self):
        self._destroy_base_of_another_vms_overlay(running=False)

    def test_destroy_keeps_the_backing_file_of_a_running_vm(self):
        self._destroy_base_of_another_vms_overlay(running=True)

    def test_destroy_with_managed_save_removes_the_vm(self):
        base = livetest.create_volume(self.conn, P + "r14-save")
        dom, inst = self.vm("r14-save", [base])
        dom.create()
        dom.managedSave(0)

        self.post("destroy", inst, {"delete_disk": "1"})

        uuid = dom.UUIDString()
        self.assertFalse(self.domain_exists(uuid), "VM is still defined")
        self.assertFalse(Instance.objects.filter(uuid=uuid).exists())

    def test_destroy_of_a_paused_vm_removes_it(self):
        base = livetest.create_volume(self.conn, P + "r14-paused")
        dom, inst = self.vm("r14-paused", [base])
        dom.create()
        dom.suspend()

        self.post("destroy", inst)

        self.assertFalse(self.domain_exists(dom.UUIDString()), "paused VM is still running")

    def nvram_files(self):
        """The test VMs' files in libvirt's NVRAM directory, read through a
        transient pool (libvirt lists files only as volumes)."""
        pool = self.conn.storagePoolCreateXML(
            f"<pool type='dir'><name>{P}nvram</name><target><path>/var/lib/libvirt/qemu/nvram</path></target></pool>", 0
        )
        try:
            return {name for name in pool.listVolumes() if name.startswith(P)}
        finally:
            pool.destroy()

    def _destroy_uefi_vm(self, data):
        dom = self.conn.defineXML(
            f"<domain type='kvm'><name>{P}r14-nvram</name><memory unit='MiB'>128</memory><vcpu>1</vcpu>"
            "<os firmware='efi'><type arch='x86_64' machine='q35'>hvm</type></os>"
            "<features><acpi/></features><devices/></domain>"
        )
        refr(self.compute)
        inst = Instance.objects.get(compute=self.compute, uuid=dom.UUIDString())
        dom.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)  # creates the NVRAM file
        dom.destroy()
        self.assertIn(f"{P}r14-nvram_VARS.fd", self.nvram_files())

        self.post("destroy", inst, data)

        self.assertFalse(self.domain_exists(dom.UUIDString()), "VM is still defined")
        return f"{P}r14-nvram_VARS.fd" in self.nvram_files()

    def test_destroy_deletes_the_nvram_when_asked(self):
        self.assertFalse(self._destroy_uefi_vm({"delete_nvram": "1"}), "the NVRAM file is still there")

    def test_destroy_keeps_the_nvram_otherwise(self):
        try:
            self.assertTrue(self._destroy_uefi_vm({}), "the NVRAM file was deleted")
        finally:
            pool = self.conn.storagePoolCreateXML(
                f"<pool type='dir'><name>{P}nvram</name><target><path>/var/lib/libvirt/qemu/nvram</path></target></pool>", 0
            )
            try:
                for name in pool.listVolumes():
                    if name.startswith(P):
                        pool.storageVolLookupByName(name).delete(0)
            finally:
                pool.destroy()

    def test_destroy_of_an_overlay_keeps_its_base(self):
        # The base may be a template other images grow from; only the VM's
        # own top image goes, with the snapshot metadata.
        base = livetest.create_volume(self.conn, P + "r14-chain-base")
        pool = self.conn.storagePoolLookupByName(livetest.POOL)
        overlay = pool.createXML(
            f"<volume><name>{P}r14-chain.qcow2</name><capacity unit='MiB'>64</capacity>"
            f"<target><format type='qcow2'/></target><backingStore><path>{base}</path>"
            "<format type='qcow2'/></backingStore></volume>",
            0,
        ).path()
        dom, inst = self.vm("r14-chain", [overlay])
        dom.snapshotCreateXML("<domainsnapshot><name>snap</name></domainsnapshot>", 0)

        response = self.post("destroy", inst, {"delete_disk": "1"})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.domain_exists(dom.UUIDString()), "VM is still defined")
        self.assertFalse(livetest.volume_exists(self.conn, overlay), "the VM's own image is still there")
        self.assertTrue(livetest.volume_exists(self.conn, base), "the base image was deleted")

    def test_destroy_deletes_the_external_snapshot_chain_but_not_its_template(self):
        # The VM grew from a template; its snapshots added overlays above its
        # disk and saved memory. Deleting the disks takes all of those, which
        # nothing else uses once the VM and its snapshot metadata are gone.
        template = livetest.create_volume(self.conn, P + "r14-ext-template")
        pool = self.conn.storagePoolLookupByName(livetest.POOL)
        disk = pool.createXML(
            f"<volume><name>{P}r14-ext.qcow2</name><capacity unit='MiB'>64</capacity>"
            f"<target><format type='qcow2'/></target><backingStore><path>{template}</path>"
            "<format type='qcow2'/></backingStore></volume>",
            0,
        ).path()
        dom, inst = self.vm("r14-ext", [disk])
        dom.create()
        inst.proxy.create_external_snapshot("a", memory=True)
        inst.proxy.create_external_snapshot("b")
        memory = os.path.join(livetest.POOL_PATH, f"{dom.UUIDString()}.a.mem")
        pool.refresh(0)
        made = {name for name in pool.listVolumes() if name.startswith(P + "r14-ext.")} - {P + "r14-ext.qcow2"}
        self.assertEqual(len(made), 2, made)  # one overlay per snapshot

        response = self.post("destroy", inst, {"delete_disk": "1"})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.domain_exists(dom.UUIDString()), "VM is still defined")
        pool.refresh(0)
        left = {name for name in pool.listVolumes() if name.startswith(P + "r14-ext") and "template" not in name}
        self.assertEqual(left, set(), "files of the VM or its snapshots stayed")
        self.assertFalse(livetest.volume_exists(self.conn, memory), "the memory file stayed")
        self.assertTrue(livetest.volume_exists(self.conn, template), "the template was deleted")
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request) if "kept" in str(m)], [])

    def test_destroy_after_a_revert_deletes_the_newer_snapshots_files_too(self):
        base = livetest.create_volume(self.conn, P + "r14-rev")
        dom, inst = self.vm("r14-rev", [base])
        inst.proxy.create_external_snapshot("a")
        inst.proxy.create_external_snapshot("b")
        inst.proxy.revert_external_snapshot("a")  # b's overlay is off the disk's chain now

        response = self.post("destroy", inst, {"delete_disk": "1"})

        self.assertEqual(response.status_code, 302)
        pool = self.conn.storagePoolLookupByName(livetest.POOL)
        pool.refresh(0)
        self.assertEqual({name for name in pool.listVolumes() if name.startswith(P + "r14-rev")}, set())

    # Delete a volume from the storage page

    def test_the_storage_page_keeps_volumes_a_vm_needs(self):
        disk = livetest.create_volume(self.conn, P + "vol-disk")
        dom, inst = self.vm("vol-disk", [disk])
        inst.proxy.create_external_snapshot("a")  # disk is now the file snapshot a was taken on
        template = livetest.create_volume(self.conn, P + "vol-template")
        pool = self.conn.storagePoolLookupByName(livetest.POOL)
        pool.createXML(
            f"<volume><name>{P}vol-clone.qcow2</name><capacity unit='MiB'>64</capacity>"
            f"<target><format type='qcow2'/></target><backingStore><path>{template}</path>"
            "<format type='qcow2'/></backingStore></volume>",
            0,
        )
        unused = livetest.create_volume(self.conn, P + "vol-unused")
        top = self.disk_sources(dom)["vda"]
        url = reverse("storage", args=[self.compute.id, livetest.POOL])

        for path in (disk, template, top):
            with self.subTest(path):
                response = self.client.post(url, {"del_volume": "1", "volname": os.path.basename(path)})
                self.assertEqual(response.status_code, 302)
                self.assertTrue(livetest.volume_exists(self.conn, path), "a volume a VM needs was deleted")
                self.assertTrue(any("is in use" in str(m) for m in get_messages(response.wsgi_request)))
        self.client.post(url, {"del_volume": "1", "volname": os.path.basename(unused)})
        self.assertFalse(livetest.volume_exists(self.conn, unused), "an unused volume was kept")

    # Delete a volume only after it is detached

    def _delete_attached_volume(self, pause):
        base = livetest.create_volume(self.conn, P + "s02")
        data = livetest.create_volume(self.conn, P + "s02-data")
        dom, inst = self.vm("s02", [base, data])
        dom.create()
        if pause:
            dom.suspend()

        response = self.post("delete_vol", inst, {"dev": "vdb"})

        self.assertEqual(response.status_code, 302)

        # The guest has no OS, so it never releases the disk: the live
        # definition keeps vdb, and the volume must be kept with it.
        self.assertIn("vdb", self.disk_sources(dom))
        self.assertTrue(livetest.volume_exists(self.conn, data), "volume deleted while the VM still uses it")

    def test_delete_volume_of_a_paused_vm(self):
        self._delete_attached_volume(pause=True)

    def test_delete_volume_of_a_running_vm_without_guest_ack(self):
        self._delete_attached_volume(pause=False)

    def test_delete_volume_another_vm_uses_is_refused(self):
        base = livetest.create_volume(self.conn, P + "s02-own")
        shared = livetest.create_volume(self.conn, P + "s02-shared")
        _, inst = self.vm("s02-a", [base, shared])
        self.vm("s02-b", [shared])

        response = self.post("delete_vol", inst, {"dev": "vdb"})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(livetest.volume_exists(self.conn, shared), "deleted another VM's disk")

    # Operations follow the VM's UUID, not its name

    def test_mutation_follows_uuid_after_names_are_swapped(self):
        dom_a, inst_a = self.vm("r06-a", [])
        dom_b, _ = self.vm("r06-b", [])
        dom_a.rename(P + "r06-tmp", 0)
        dom_b.rename(P + "r06-a", 0)
        dom_a.rename(P + "r06-b", 0)

        self.post("change_options", inst_a, {"title": "for-a", "description": ""})

        self.assertIn("<title>for-a</title>", dom_a.XMLDesc(0))
        self.assertNotIn("<title>for-a</title>", dom_b.XMLDesc(0))

    def test_vm_replaced_under_the_same_name_is_not_touched(self):
        dom_old, inst = self.vm("r06-c", [])
        dom_old.undefine()
        dom_new = livetest.define_vm(self.conn, P + "r06-c", [])

        self.post("change_options", inst, {"title": "for-old", "description": ""})

        self.assertNotIn("<title>for-old</title>", dom_new.XMLDesc(0))

    # Edits of a running VM are pending until restart; the forms must show them

    def test_pending_nic_change_is_shown_and_can_be_edited_again(self):
        nic = "<interface type='network'><mac address='52:54:00:aa:05:01'/><source network='default'/></interface>"
        dom, inst = self.vm("nic-pending", [], extra_devices=nic)
        dom.create()

        def change(old, new):
            return self.post("change_network", inst, {
                "net-old-mac-0": old, "net-mac-0": new, "net-source-0": "net:default", "net-model-0": "virtio",
            })

        change("52:54:00:aa:05:01", "52:54:00:aa:05:02")
        page = self.client.get(reverse("instances:instance", args=[inst.id])).content.decode()
        self.assertIn('name="net-old-mac-0" value="52:54:00:aa:05:02"', page)

        change("52:54:00:aa:05:02", "52:54:00:aa:05:03")
        self.assertIn("52:54:00:aa:05:03", dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))

    def test_pending_disk_change_is_shown_and_kept_by_the_next_edit(self):
        from lxml import etree, html

        dom, inst = self.vm("disk-pending", [livetest.create_volume(self.conn, P + "disk-pending")])
        dom.create()
        live = dom.XMLDesc(0)

        def edit_form():
            page = self.client.get(reverse("instances:instance", args=[inst.id])).content
            action = reverse("instances:edit_volume", args=[inst.id])
            (form,) = html.fromstring(page).xpath("//form[@action=$a][.//input[@name='dev'][@value='vda']]", a=action)
            return {**dict(form.form_values()), "edit_volume": ""}  # what the browser posts

        self.post("edit_volume", inst, {**edit_form(), "vol_cache": "none"})
        form = edit_form()
        self.assertEqual(form["vol_cache"], "none")
        self.post("edit_volume", inst, {**form, "vol_serial": "wvc-serial"})

        disk = etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)).find("devices/disk")
        self.assertEqual((disk.find("driver").get("cache"), disk.findtext("serial")), ("none", "wvc-serial"))
        self.assertEqual(dom.XMLDesc(0), live)

    def test_pending_options_and_cpu_changes_are_shown_and_kept_by_the_next_edit(self):
        from lxml import etree, html

        dom, inst = self.vm("options-pending", [])
        dom.create()
        live = dom.XMLDesc(0)

        def form(view):
            page = self.client.get(reverse("instances:instance", args=[inst.id])).content
            (form,) = html.fromstring(page).xpath("//form[@action=$a]", a=reverse(f"instances:{view}", args=[inst.id]))
            return dict(form.form_values())  # what the form would post

        # the buttons are disabled while it runs; a direct post is pending
        self.post("change_options", inst, {**form("change_options"), "title": "wvc-title"})
        self.post("resizevm_cpu", inst, {**form("resizevm_cpu"), "vcpu": "2"})
        options, cpu = form("change_options"), form("resizevm_cpu")
        self.assertEqual((options["title"], cpu["vcpu"]), ("wvc-title", "2"))
        self.post("change_options", inst, {**options, "description": "wvc-description"})
        self.post("resizevm_cpu", inst, {**cpu, "cur_vcpu": "1"})

        tree = etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
        self.assertEqual((tree.findtext("title"), tree.findtext("description"), tree.findtext("vcpu")),
                         ("wvc-title", "wvc-description", "2"))
        self.assertEqual(dom.XMLDesc(0), live)

    def test_pending_boot_order_and_video_are_shown_and_a_live_only_choice_changes_nothing(self):
        from lxml import etree, html

        nic = "<interface type='network'><mac address='52:54:00:aa:05:21'/><source network='default'/></interface>"
        graphics = "<graphics type='vnc' autoport='yes' listen='127.0.0.1'/>"
        dom, inst = self.vm("boot-pending", [livetest.create_volume(self.conn, P + "boot-pending")],
                            extra_devices=nic + graphics)
        self.post("set_bootmenu", inst)
        dom.create()
        # pending order; a NIC the running VM has but its next start will not
        self.post("set_bootorder", inst, {"bootorder": "network:52:54:00:aa:05:21,disk:vda"})
        dom.attachDeviceFlags(nic.replace("05:21", "05:22"), libvirt.VIR_DOMAIN_AFFECT_LIVE)
        persistent = lambda: etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))  # noqa: E731
        video = "virtio" if persistent().find("devices/video/model").get("type") != "virtio" else "vga"
        self.post("set_video_model", inst, {"video_model": video})
        live = dom.XMLDesc(0)

        page = html.fromstring(self.client.get(reverse("instances:instance", args=[inst.id])).content)
        (boot,) = page.xpath("//form[@action=$a]", a=reverse("instances:set_bootorder", args=[inst.id]))
        self.assertEqual(boot.xpath(".//input[@type='checkbox']/@value"), ["disk:vda", "network:52:54:00:aa:05:21"])
        self.assertEqual(page.xpath("//select[@name='video_model']/option[@selected]/@value"), [video])

        self.post("set_bootorder", inst, {"bootorder": "network:52:54:00:aa:05:22,disk:vda"})
        tree = persistent()
        self.assertEqual(tree.xpath("devices/interface/boot/@order"), ["1"])
        self.assertEqual(tree.xpath("devices/disk[target/@dev='vda']/boot/@order"), ["2"])
        self.assertEqual(dom.XMLDesc(0), live)

    def test_a_new_disk_does_not_take_a_name_pending_in_the_persistent_definition(self):
        from lxml import html

        disks = [livetest.create_volume(self.conn, P + n) for n in ("name-a", "name-b")]
        dom, inst = self.vm("disk-name", disks, extra_devices="<controller type='scsi' model='virtio-scsi'/>")
        dom.create()
        # vdb becomes sata: renamed sda in the persistent definition only
        page = self.client.get(reverse("instances:instance", args=[inst.id])).content
        action = reverse("instances:edit_volume", args=[inst.id])
        (form,) = html.fromstring(page).xpath("//form[@action=$a][.//input[@name='dev'][@value='vdb']]", a=action)
        self.post("edit_volume", inst, {**dict(form.form_values()), "edit_volume": "", "vol_bus": "sata"})
        self.assertEqual(self.disk_sources(dom, libvirt.VIR_DOMAIN_XML_INACTIVE).get("sda"), disks[1])

        # scsi shares the sd names: the new disk must not be sda
        self.post("add_new_vol", inst, {"storage": livetest.POOL, "name": P + "name-new", "format": "qcow2",
                                        "size": "1", "bus": "scsi", "cache": "default"})
        new = f"{livetest.POOL_PATH}/{P}name-new.qcow2"
        self.assertEqual(self.disk_sources(dom).get("sdb"), new)
        self.assertEqual(self.disk_sources(dom, libvirt.VIR_DOMAIN_XML_INACTIVE).get("sdb"), new)
        dom.destroy()
        dom.create()
        self.assertEqual(self.disk_sources(dom), {"vda": disks[0], "sda": disks[1], "sdb": new})

    def test_a_sata_disk_cannot_be_added_to_a_running_vm_and_nothing_changes(self):
        dom, inst = self.vm("sata-hotplug", [livetest.create_volume(self.conn, P + "sata-a")])
        dom.create()
        before = (self.disk_sources(dom), self.disk_sources(dom, libvirt.VIR_DOMAIN_XML_INACTIVE))
        response = self.post("add_new_vol", inst, {"storage": livetest.POOL, "name": P + "sata-new", "format": "qcow2",
                                                   "size": "1", "bus": "sata", "cache": "default"})
        # libvirt refuses it: the form goes back to the VM page with the reason
        self.assertRedirects(response, reverse("instances:instance", args=[inst.id]), fetch_redirect_response=False)
        self.assertTrue(any("libvirt Error" in str(m) for m in get_messages(response.wsgi_request)))
        self.assertEqual((self.disk_sources(dom), self.disk_sources(dom, libvirt.VIR_DOMAIN_XML_INACTIVE)), before)
        # the new volume stays in the pool: it is never deleted unasked
        self.assertIn(P + "sata-new.qcow2", self.conn.storagePoolLookupByName(livetest.POOL).listVolumes())

    def test_an_attach_that_conflicts_with_a_pending_device_changes_neither_definition(self):
        controllers = "<controller type='scsi' index='0' model='virtio-scsi'/><controller type='virtio-serial'/>"
        def disk(path):
            return (f"<disk type='file' device='disk'><driver name='qemu' type='qcow2'/><source file='{path}'/>"
                    "<target dev='sda' bus='scsi'/></disk>")

        agent = "<channel type='unix'><target type='virtio' name='org.qemu.guest_agent.0'/></channel>"
        cases = (
            ("disk", lambda n: disk(livetest.create_volume(self.conn, P + n + "-pending")),
             lambda vm, n: vm.attach_disk("sda", livetest.create_volume(self.conn, P + n + "-new"),
                                          target_bus="scsi", format_type="qcow2")),
            ("agent", lambda n: agent, lambda vm, n: vm.add_guest_agent()),
        )
        both = (0, libvirt.VIR_DOMAIN_XML_INACTIVE)
        for paused in (False, True):
            for case, pending, attach in cases:
                with self.subTest(case=case, paused=paused):
                    name = f"attach-{case}-{int(paused)}"  # own volumes: a leftover plug must not lock them
                    dom, inst = self.vm(name, [], extra_devices=controllers)
                    dom.create()
                    dom.attachDeviceFlags(pending(name), libvirt.VIR_DOMAIN_AFFECT_CONFIG)  # pending: persistent only
                    if paused:
                        dom.suspend()
                    before = [dom.XMLDesc(flags) for flags in both]
                    with self.assertRaises(libvirt.libvirtError):
                        attach(inst.proxy, name)
                    self.assertEqual([dom.XMLDesc(flags) for flags in both], before)

    def test_a_nic_without_a_mac_gets_the_same_one_in_both_definitions(self):
        from lxml import etree

        nic = "<interface type='network'><mac address='52:54:00:aa:18:09'/><source network='default'/></interface>"
        dom, inst = self.vm("nic-mac", [], extra_devices=nic)
        dom.create()
        self.post("add_network", inst, {"add-net-network": "net:default", "add-net-mac": "", "add-net-model": "virtio"})

        def macs(flags):
            return set(etree.fromstring(dom.XMLDesc(flags)).xpath("devices/interface/mac/@address")) - {"52:54:00:aa:18:09"}

        self.assertEqual(len(macs(0)), 1)
        self.assertEqual(macs(libvirt.VIR_DOMAIN_XML_INACTIVE), macs(0))

    def test_an_empty_scsi_cdrom_reaches_both_definitions_of_a_running_vm(self):
        from lxml import etree

        dom, inst = self.vm("cdrom-scsi", [], extra_devices="<controller type='scsi' index='0' model='virtio-scsi'/>")
        dom.create()
        self.post("add_cdrom", inst, {"bus": "scsi"})
        for flags in (0, libvirt.VIR_DOMAIN_XML_INACTIVE):
            tree = etree.fromstring(dom.XMLDesc(flags))
            self.assertEqual(tree.xpath("devices/disk[@device='cdrom']/target/@dev"), ["sda"])

    def test_pending_qos_change_is_shown_and_kept_by_the_next_edit(self):
        from lxml import etree, html

        mac = "52:54:00:aa:05:11"
        nic = (f"<interface type='network'><mac address='{mac}'/><source network='default'/>"
               "<bandwidth><inbound average='500' peak='0' burst='0'/></bandwidth></interface>")
        dom, inst = self.vm("qos-pending", [], extra_devices=nic)
        dom.create()
        live = dom.XMLDesc(0)

        def row():
            page = html.fromstring(self.client.get(reverse("instances:instance", args=[inst.id])).content)
            (label,) = page.xpath("//label[@class='col-form-label'][contains(., 'Inbound')]")
            fields = label.xpath("ancestor::tr[1]//input[@name]")  # the browser posts the row's inputs
            return {f.get("name"): f.get("value") for f in fields}

        self.post("set_qos", inst, {**row(), "qos_average": "1000"})
        form = row()
        self.assertEqual(form["qos_average"], "1000")
        self.post("set_qos", inst, {**form, "qos_peak": "600"})

        inbound = etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)).find("devices/interface/bandwidth/inbound")
        self.assertEqual((inbound.get("average"), inbound.get("peak")), ("1000", "600"))
        self.assertEqual(dom.XMLDesc(0), live)

