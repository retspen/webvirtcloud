import re
import unittest

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from vrtManager.util import (
    compareMAC,
    get_xml_path,
    is_kvm_available,
    pretty_bytes,
    pretty_mem,
    randomMAC,
    randomPasswd,
    randomUUID,
    validate_macaddr,
    validate_uuid,
    vol_dev_type,
    xml_escape,
)


class TestVrtManagerUtil(unittest.TestCase):
    def test_random_uuid_format(self):
        uuid_str = randomUUID()
        # UUIDv4 format check
        pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        self.assertRegex(uuid_str, pattern)
        # Ensure successive UUIDs are distinct
        self.assertNotEqual(uuid_str, randomUUID())

    def test_validate_uuid(self):
        valid_dashed = "c9a646d3-9c61-4cd8-8024-f6b72a6642d9"
        self.assertEqual(validate_uuid(valid_dashed), valid_dashed)

        valid_no_dash = "c9a646d39c614cd88024f6b72a6642d9"
        self.assertEqual(validate_uuid(valid_no_dash), valid_dashed)

        with self.assertRaises(ValueError):
            validate_uuid("invalid-uuid-too-short")

        with self.assertRaises(ValueError):
            validate_uuid(12345)

    def test_random_mac(self):
        mac = randomMAC()
        self.assertTrue(mac.startswith("52:54:10:"))
        parts = mac.split(":")
        self.assertEqual(len(parts), 6)
        for part in parts:
            self.assertEqual(len(part), 2)
            int(part, 16)  # valid hex

    def test_compare_mac(self):
        mac1 = "52:54:10:00:00:01"
        mac2 = "52:54:10:00:00:02"
        self.assertEqual(compareMAC(mac1, mac1), 0)
        self.assertEqual(compareMAC(mac1, mac2), -1)
        self.assertEqual(compareMAC(mac2, mac1), 1)
        # Different lengths
        self.assertEqual(compareMAC("52:54", "52:54:10"), -1)
        self.assertEqual(compareMAC("52:54:10", "52:54"), 1)

    def test_validate_macaddr(self):
        self.assertIsNone(validate_macaddr(None))
        self.assertIsNone(validate_macaddr("52:54:10:aa:bb:cc"))
        self.assertIsNone(validate_macaddr("0:1:2:3:4:5"))

        with self.assertRaises(ValueError):
            validate_macaddr("invalid_mac")

        with self.assertRaises(ValueError):
            validate_macaddr(12345)

    def test_random_passwd(self):
        pwd = randomPasswd(16)
        self.assertEqual(len(pwd), 16)
        # Custom alphabet
        numeric_pwd = randomPasswd(10, alphabet="0123456789")
        self.assertEqual(len(numeric_pwd), 10)
        self.assertTrue(numeric_pwd.isdigit())

    def test_xml_escape(self):
        self.assertIsNone(xml_escape(None))
        escaped = xml_escape('<foo name="bar" test=\'baz\' &/>')
        self.assertEqual(escaped, "&lt;foo name=&quot;bar&quot; test=&apos;baz&apos; &amp;/&gt;")

    def test_get_xml_path(self):
        xml = "<domain type='kvm'><name>testvm</name><memory unit='KiB'>1048576</memory></domain>"
        self.assertEqual(get_xml_path(xml, "/domain/name"), "testvm")
        self.assertEqual(get_xml_path(xml, "/domain/memory"), "1048576")
        self.assertEqual(get_xml_path(xml, "/domain/@type"), "kvm")

        # Function callback mode
        def extract_name(doc):
            return doc.xpath("/domain/name")[0].text

        self.assertEqual(get_xml_path(xml, func=extract_name), "testvm")

        # Missing both path and func
        with self.assertRaises(ValueError):
            get_xml_path(xml)

    def test_is_kvm_available(self):
        kvm_xml = "<capabilities><guest><arch name='x86_64'><domain type='kvm'/></arch></guest></capabilities>"
        qemu_xml = "<capabilities><guest><arch name='x86_64'><domain type='qemu'/></arch></guest></capabilities>"
        self.assertTrue(is_kvm_available(kvm_xml))
        self.assertFalse(is_kvm_available(qemu_xml))

    def test_pretty_mem(self):
        # Value in KB
        self.assertEqual(pretty_mem(1024), " 1 MB")
        self.assertEqual(pretty_mem(1024 * 1024), "1024 MB")
        self.assertEqual(pretty_mem(16 * 1024 * 1024), "16.00 GB")

    def test_pretty_bytes(self):
        # Value in Bytes
        self.assertEqual(pretty_bytes(10 * 1024 * 1024), "10.00 MB")
        self.assertEqual(pretty_bytes(2 * 1024 * 1024 * 1024), "2.00 GB")

    def test_vol_dev_type(self):
        self.assertEqual(vol_dev_type("ide"), "hd")
        self.assertEqual(vol_dev_type("fdc"), "fd")
        self.assertEqual(vol_dev_type("virtio"), "vd")
        self.assertEqual(vol_dev_type("scsi"), "sd")
        self.assertEqual(vol_dev_type("sata"), "sd")
        self.assertIsNone(vol_dev_type("unknown_bus"))


if __name__ == "__main__":
    unittest.main()
