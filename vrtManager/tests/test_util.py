import unittest

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from vrtManager.util import (
    get_xml_path,
    randomPasswd,
    randomUUID,
    validate_macaddr,
    vol_dev_type,
    vol_driver_type,
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

    def test_vol_dev_type(self):
        self.assertEqual(vol_dev_type("ide"), "hd")
        self.assertEqual(vol_dev_type("fdc"), "fd")
        self.assertEqual(vol_dev_type("virtio"), "vd")
        self.assertEqual(vol_dev_type("usb"), "sd")
        self.assertEqual(vol_dev_type("scsi"), "sd")
        self.assertEqual(vol_dev_type("sata"), "sd")
        self.assertIsNone(vol_dev_type("unknown_bus"))

    def test_vol_driver_type(self):
        for vol_format in ("qcow2", "qcow", "raw"):
            self.assertEqual(vol_driver_type(vol_format), vol_format)
        for vol_format in (None, "", "none", "unknown", "iso"):
            self.assertEqual(vol_driver_type(vol_format), "raw")
        self.assertEqual(vol_driver_type("linux-lvm", "disk"), "raw")  # a partition



class OperationErrorTestCase(unittest.TestCase):
    def test_keeps_its_own_message_after_a_libvirt_failure(self):
        import libvirt
        from vrtManager.util import OperationError

        conn = libvirt.open("test:///default")
        self.addCleanup(conn.close)
        with self.assertRaises(libvirt.libvirtError):
            conn.lookupByName("no-such-domain")  # leaves a thread-local last error
        self.assertNotEqual(str(libvirt.libvirtError("own message")), "own message")
        error = OperationError("own message")
        self.assertEqual(str(error), "own message")
        self.assertIsInstance(error, libvirt.libvirtError)

    def test_keeps_its_text_and_values_apart_for_translation(self):
        from vrtManager.util import OperationError

        error = OperationError("The pool has no volume named %(name)s", name="a.qcow2")
        self.assertEqual(str(error), "The pool has no volume named a.qcow2")
        self.assertEqual((error.text, error.values), ("The pool has no volume named %(name)s", {"name": "a.qcow2"}))
        # a text without values is not formatted: libvirt's may hold a %
        self.assertEqual(str(OperationError("100% used")), "100% used")

    def test_reads_in_the_active_language_and_keeps_english_in_its_args(self):
        from django.utils import translation
        from vrtManager.util import OperationError, message

        error = OperationError("The disks cannot be migrated: %(problems)s", problems=[
            message("%(target)s: the VM has no disk file to copy", target="vda"),
            message("%(target)s (%(path)s): %(refusal)s", target="sda", path="/i/os.iso",
                    refusal=[message("an image is not copied; eject it first")])])
        english = ("The disks cannot be migrated: vda: the VM has no disk file to copy; "
                   "sda (/i/os.iso): an image is not copied; eject it first")
        self.assertEqual(error.args[0], english)
        with translation.override("tr"):
            self.assertNotEqual(str(error), english)
            self.assertEqual(error.args[0], english)  # logs and the audit log stay English
            self.assertIn("vda", str(error))

    def test_a_job_keeps_number_values_for_their_formats(self):
        from operations.utils import said, words
        from vrtManager.util import OperationError

        error = OperationError("Storage pool %(pool)s has %(free).1f GiB free; the clone needs %(size).1f GiB "
                               "(the copied disks, plus %(percent)g%% of them, at least %(minimum)g GiB)",
                               pool="default", free=1.25, size=3.0, percent=10, minimum=2)
        self.assertEqual(words(said(error)), "Storage pool default has 1.2 GiB free; the clone needs 3.0 GiB "
                                             "(the copied disks, plus 10% of them, at least 2 GiB)")


if __name__ == "__main__":
    unittest.main()
