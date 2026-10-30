import unittest
from unittest.mock import MagicMock

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from vrtManager import util
from vrtManager.instance import wvmInstance
from vrtManager.network import wvmNetworks, wvmNetwork


class TestXmlSafety(unittest.TestCase):
    def test_create_network_escaping(self):
        wn = wvmNetworks.__new__(wvmNetworks)
        wn.wvm = MagicMock()
        mock_net = MagicMock()
        wn.get_network = MagicMock(return_value=mock_net)

        malicious_name = "net<script>alert(1)</script>&name"
        malicious_bridge = "br0' onfocus='alert(2)"

        wn.create_network(
            name=malicious_name,
            forward="bridge",
            ipv4=False,
            gateway=None,
            mask=None,
            dhcp4=None,
            ipv6=False,
            gateway6=None,
            prefix6=None,
            dhcp6=None,
            bridge=malicious_bridge,
            openvswitch=False,
        )

        wn.wvm.networkDefineXML.assert_called_once()
        defined_xml = wn.wvm.networkDefineXML.call_args[0][0]
        self.assertNotIn("<script>", defined_xml)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;&amp;name", defined_xml)
        self.assertIn("name='br0&apos; onfocus=&apos;alert(2)'", defined_xml)

    def test_network_set_qos_validation(self):
        wn = wvmNetwork.__new__(wvmNetwork)
        wn._XMLDesc = MagicMock(return_value="<network><name>testnet</name></network>")
        wn.wvm = MagicMock()

        # Invalid direction
        with self.assertRaises(ValueError):
            wn.set_qos("lateral", 100, 200, 300)

        # Invalid numeric strings
        with self.assertRaises(ValueError):
            wn.set_qos("inbound", "not_a_number", 200, 300)

    def test_snapshot_xml_payload_is_escaped(self):
        inst = wvmInstance.__new__(wvmInstance)
        inst.instance = MagicMock(**{"snapshotListNames.return_value": [], "hasManagedSaveImage.return_value": 0})  # no snapshots yet
        inst.get_snapshot_jobs = MagicMock(return_value=[])
        inst.get_status = MagicMock(return_value=5)  # shutoff
        inst._XMLDesc = MagicMock(return_value="<domain></domain>")
        inst._snapshotCreateXML = MagicMock(return_value=None)

        bad_name = "snap<inject>&quotes"
        bad_desc = "desc<tag>&and"

        inst.create_snapshot(bad_name, bad_desc)

        inst._snapshotCreateXML.assert_called_once()
        created_xml = inst._snapshotCreateXML.call_args[0][0]
        self.assertNotIn("<inject>", created_xml)
        self.assertNotIn("<tag>", created_xml)
        self.assertIn("&lt;inject&gt;&amp;quotes", created_xml)
        self.assertIn("&lt;tag&gt;&amp;and", created_xml)

    def test_original_rom_loader_preserved(self):
        inst = wvmInstance.__new__(wvmInstance)
        inst.instance = MagicMock(**{"snapshotListNames.return_value": [], "hasManagedSaveImage.return_value": 0})  # no snapshots yet
        inst.get_snapshot_jobs = MagicMock(return_value=[])
        inst._XMLDesc = MagicMock(return_value="<domain><os><loader type='rom'>/usr/share/rom.bin</loader></os></domain>")
        inst._defineXML = MagicMock()
        inst._snapshotCreateXML = MagicMock(return_value=None)
        inst.get_status = MagicMock(return_value=5)

        inst.create_snapshot("snap_rom", "testing rom preservation")
        inst._defineXML.assert_not_called()

    def test_snapshot_revert_rom_loader_preserved(self):
        inst = wvmInstance.__new__(wvmInstance)
        inst.instance = MagicMock(**{"snapshotListNames.return_value": ["snap_rom"], "hasManagedSaveImage.return_value": 0})
        inst.get_snapshot_jobs = MagicMock(return_value=[])
        inst.get_status = MagicMock(return_value=5)  # an internal snapshot is reverted to on a shut-off VM
        mock_snap = MagicMock()
        inst.instance.snapshotLookupByName = MagicMock(return_value=mock_snap)
        inst.instance.revertToSnapshot = MagicMock()
        inst._defineXML = MagicMock()

        inst.snapshot_revert("snap_rom")

        inst.instance.snapshotLookupByName.assert_called_once_with("snap_rom", 0)
        inst.instance.revertToSnapshot.assert_called_once_with(mock_snap, 0)
        inst._defineXML.assert_not_called()

    def test_internal_snapshot_never_rewrites_a_pflash_loader(self):
        # libvirt decides; the definition is not switched to rom.
        inst = wvmInstance.__new__(wvmInstance)
        inst.instance = MagicMock(**{"snapshotListNames.return_value": [], "hasManagedSaveImage.return_value": 0})  # no snapshots yet
        inst.get_snapshot_jobs = MagicMock(return_value=[])
        inst.get_status = MagicMock(return_value=5)
        inst._XMLDesc = MagicMock(
            return_value="<domain><os><loader readonly='yes' type='pflash'>/usr/share/OVMF/OVMF.fd</loader></os></domain>"
        )
        inst._defineXML = MagicMock()
        inst._snapshotCreateXML = MagicMock()

        inst.create_snapshot("snap", "uefi")

        inst._defineXML.assert_not_called()
        self.assertIn("type='pflash'", inst._snapshotCreateXML.call_args[0][0])



class TestCloneRollback(unittest.TestCase):
    """A failed clone removes only the volumes it created."""

    def test_copies_are_removed_when_the_definition_fails(self):
        import libvirt

        inst = wvmInstance.__new__(wvmInstance)
        inst.wvm = MagicMock()
        inst.get_status = MagicMock(return_value=5)
        inst.get_instances = MagicMock(return_value=[])
        inst.get_nvram = MagicMock(return_value=None)
        inst._XMLDesc = MagicMock(return_value=(
            "<domain><name>src</name><devices>"
            "<disk type='file' device='disk'><source file='/pool/src.qcow2'/><target dev='vda'/></disk>"
            "</devices></domain>"
        ))
        source_vol = MagicMock()
        source_vol.XMLDesc.return_value = "<volume><target><format type='qcow2'/></target></volume>"
        copy = MagicMock()
        copy.path.return_value = "/pool/copy.qcow2"
        source_vol.storagePoolLookupByVolume.return_value.createXMLFrom.return_value = copy
        inst.get_volume_by_path = MagicMock(side_effect=lambda path: copy if path == "/pool/copy.qcow2" else source_vol)
        inst._defineXML = MagicMock(side_effect=libvirt.libvirtError("bad definition"))

        with self.assertRaises(libvirt.libvirtError):
            inst.clone_instance({"name": "copy", "disk-vda": "copy.qcow2", "disk_owner_uid": 0, "disk_owner_gid": 0}, "abababab-0000-1111-2222-333333333333")
        copy.delete.assert_called_once_with(0)
        source_vol.delete.assert_not_called()

    def test_running_vm_is_refused_before_anything_is_read(self):
        import libvirt

        inst = wvmInstance.__new__(wvmInstance)
        inst.get_status = MagicMock(return_value=1)
        inst._XMLDesc = MagicMock()
        with self.assertRaisesRegex(libvirt.libvirtError, "Shut the VM down"):
            inst.clone_instance({"name": "copy"}, "abababab-0000-1111-2222-333333333333")
        inst._XMLDesc.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class TestDiskXmlEscaping(unittest.TestCase):
    def _instance(self):
        inst = wvmInstance.__new__(wvmInstance)
        inst.get_status = MagicMock(return_value=5)  # shutoff
        inst.instance = MagicMock()
        inst._defineXML = MagicMock()
        return inst

    def test_attach_disk_escapes_source_and_serial(self):
        inst = self._instance()
        inst.attach_disk(
            "vdb",
            "/images/a'/><disk type='file",
            target_bus="virtio",
            disk_type="file",
            serial="S1</serial><evil/>",
        )
        xml = inst.instance.attachDeviceFlags.call_args[0][0]
        self.assertIn("file='/images/a&apos;/&gt;&lt;disk type=&apos;file'", xml)
        self.assertIn("<serial>S1&lt;/serial&gt;&lt;evil/&gt;</serial>", xml)
        self.assertNotIn("<evil/>", xml)

    def test_edit_disk_escapes_source_and_serial(self):
        inst = self._instance()
        inst._XMLDesc = MagicMock(
            return_value=(
                "<domain><devices><disk type='file' device='disk'>"
                "<driver name='qemu' type='qcow2'/>"
                "<source file='/images/vm.qcow2'/>"
                "<target dev='vda' bus='virtio'/>"
                "</disk></devices></domain>"
            )
        )
        inst.edit_disk(
            "vda",
            "/images/b'/><x y='",
            False,
            False,
            "virtio",
            "S2<evil/>",
            "qcow2",
            "default",
            "default",
            "default",
            "default",
        )
        xml = inst._defineXML.call_args.args[0]
        from lxml import etree
        self.assertEqual(etree.fromstring(xml).find("devices/disk/source").get("file"), "/images/b'/><x y='")
        self.assertNotIn("<evil/>", xml)

    def test_detach_disk_does_not_evaluate_dev_as_xpath(self):
        inst = self._instance()
        inst._XMLDesc = MagicMock(
            return_value=(
                "<domain><devices><disk type='file' device='disk'>"
                "<source file='/images/vm.qcow2'/>"
                "<target dev='vda' bus='virtio'/>"
                "</disk></devices></domain>"
            )
        )
        with self.assertRaises(util.OperationError):
            inst.detach_disk("x' or '1'='1")
        inst.instance.detachDeviceFlags.assert_not_called()


class TestPersistentDiskEditing(unittest.TestCase):
    def setUp(self):
        import libvirt
        from lxml import etree

        self.conn = libvirt.open("test:///default")
        self.addCleanup(self.conn.close)
        self.domain = self.conn.lookupByName("test")
        original = self.domain.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE | libvirt.VIR_DOMAIN_XML_SECURE)
        self.addCleanup(self.conn.defineXML, original)
        config = etree.fromstring(original)
        disk = config.find("devices/disk")
        disk.set("type", "file")
        driver = disk.find("driver")
        if driver is None:
            driver = etree.SubElement(disk, "driver")
        driver.set("name", "qemu")
        driver.set("type", "qcow2")
        driver.set("queues", "4")
        etree.SubElement(disk, "address", type="pci", slot="0x05")
        encryption = etree.SubElement(disk, "encryption", format="luks")
        etree.SubElement(encryption, "secret", type="passphrase", uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        etree.SubElement(etree.SubElement(disk, "iotune"), "total_bytes_sec").text = "1024"
        # A pending change and a VNC password outside the edited disk must survive.
        config.find("memory").text = "123456"
        etree.SubElement(config.find("devices"), "graphics", type="vnc", passwd="keep-secret")
        self.conn.defineXML(etree.tostring(config).decode())
        self.inst = wvmInstance.__new__(wvmInstance)
        self.inst.wvm = self.conn
        self.inst.instance = self.domain
        self.target = disk.find("target").get("dev")

    def config(self):
        import libvirt
        from lxml import etree
        return etree.fromstring(self.domain.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE | libvirt.VIR_DOMAIN_XML_SECURE))

    def edit(self, bus="virtio", format="qcow2"):
        self.inst.edit_disk(
            self.target, "/images/a'<new>&.qcow2", False, False, bus,
            "serial<&", format, "none", "native", "unmap", "on",
        )

    def test_running_bus_change_preserves_disk_and_pending_domain_configuration(self):
        self.assertTrue(self.domain.isActive())
        live_before = self.domain.XMLDesc(0)
        self.edit(bus="sata")
        config = self.config()
        disk = config.find("devices/disk")
        self.assertEqual(disk.find("target").get("bus"), "sata")
        self.assertTrue(disk.find("target").get("dev").startswith("sd"))
        self.assertNotEqual(disk.find("address").get("type"), "pci")
        self.assertIsNone(disk.find("driver").get("queues"))
        self.assertEqual(disk.find("driver").get("cache"), "none")
        self.assertEqual(disk.findtext("iotune/total_bytes_sec"), "1024")
        self.assertEqual(disk.find("encryption/secret").get("uuid"), "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertEqual(disk.find("source").get("file"), "/images/a'<new>&.qcow2")
        self.assertEqual(disk.findtext("serial"), "serial<&")
        self.assertEqual(config.findtext("memory"), "123456")
        self.assertEqual(config.find("devices/graphics").get("passwd"), "keep-secret")
        self.assertEqual(self.domain.XMLDesc(0), live_before)
        # The resulting disk can be edited again before the VM restarts.
        self.target = disk.find("target").get("dev")
        self.edit(bus="sata")
        self.assertEqual(self.config().find("devices/disk/target").get("dev"), self.target)

    def test_failed_definition_leaves_the_original_configuration_intact(self):
        from libvirt import libvirtError
        from unittest.mock import patch
        before = self.domain.XMLDesc(2)
        with patch.object(self.inst, "_defineXML", side_effect=libvirtError("definition failed")):
            with self.assertRaises(libvirtError):
                self.edit(bus="sata")
        self.assertEqual(self.domain.XMLDesc(2), before)

    def test_network_disk_keeps_auth_source_and_encryption(self):
        from lxml import etree
        config = self.config()
        disk = config.find("devices/disk")
        disk.set("type", "network")
        disk.remove(disk.find("source"))
        source = etree.SubElement(disk, "source", protocol="rbd", name="pool/vm-disk")
        etree.SubElement(source, "host", name="mon1", port="6789")
        auth = etree.SubElement(disk, "auth", username="libvirt")
        etree.SubElement(auth, "secret", type="ceph", uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.conn.defineXML(etree.tostring(config).decode())
        self.edit(bus="sata")
        result = self.config().find("devices/disk")
        self.assertEqual(result.find("source").get("name"), "pool/vm-disk")
        self.assertEqual(result.find("source/host").get("name"), "mon1")
        self.assertEqual(result.find("auth").get("username"), "libvirt")
        self.assertIsNotNone(result.find("encryption"))

    def test_empty_format_omits_driver_type(self):
        self.edit(format="")
        self.assertIsNone(self.config().find("devices/disk/driver").get("type"))

    def test_virtio_options_survive_editing_on_the_same_bus(self):
        self.edit()
        self.assertEqual(self.config().find("devices/disk/driver").get("queues"), "4")


class TestEmptyDiskClone(unittest.TestCase):
    def test_clone_omits_empty_disks_before_real_libvirt_definition(self):
        import libvirt
        from lxml import etree

        conn = libvirt.open("test:///default")
        self.addCleanup(conn.close)
        domain = conn.lookupByName("test")
        config = etree.fromstring(domain.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
        devices = config.find("devices")
        for disk in devices.findall("disk"):
            source = disk.find("source")
            if source is not None:
                disk.remove(source)
        for interface in devices.findall("interface"):
            devices.remove(interface)
        inst = wvmInstance.__new__(wvmInstance)
        inst.wvm = conn
        inst.instance = domain
        # Exercise defensive handling of incomplete disk metadata, while the
        # clone is still defined and looked up through the real test driver.
        inst._XMLDesc = MagicMock(return_value=etree.tostring(config).decode())
        inst.get_status = MagicMock(return_value=5)  # only shut-off VMs are cloned
        clone_uuid = inst.clone_instance({"name": "empty-disk-clone"}, "abababab-0000-1111-2222-333333333333")
        clone = conn.lookupByUUIDString(clone_uuid)
        self.addCleanup(clone.undefine)
        clone_config = etree.fromstring(clone.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
        self.assertEqual(clone_config.findtext("name"), "empty-disk-clone")
        self.assertEqual(clone_config.findall("devices/disk"), [])
        self.assertTrue(config.findall("devices/disk"))

    def test_clone_rejects_existing_name_before_allocating_storage(self):
        import libvirt

        conn = libvirt.open("test:///default")
        self.addCleanup(conn.close)
        inst = wvmInstance.__new__(wvmInstance)
        inst.wvm = conn
        inst.instance = conn.lookupByName("test")
        inst._XMLDesc = MagicMock()
        inst.get_status = MagicMock(return_value=5)
        with self.assertRaisesRegex(ValueError, "already exists"):
            inst.clone_instance({"name": "test"}, "abababab-0000-1111-2222-333333333333")
        inst._XMLDesc.assert_not_called()
