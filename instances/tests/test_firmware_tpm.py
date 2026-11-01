"""A new VM's firmware and TPM: the choices come from the host's domain
capabilities, UEFI is libvirt's firmware autoselection (Secure Boot with
Microsoft's keys enrolled, as Windows 11 needs) and a TPM is an emulated
TPM 2.0 (swtpm)."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from lxml import etree
from vrtManager.connection import wvmConnect
from vrtManager.create import wvmCreate

FULL = """<domainCapabilities><os supported='yes'>
  <enum name='firmware'><value>efi</value></enum>
  <firmwareFeatures supported='yes'>
    <enum name='secureBoot'><value>yes</value><value>no</value></enum>
    <enum name='enrolledKeys'><value>yes</value><value>no</value></enum>
  </firmwareFeatures>
</os><devices><tpm supported='yes'>
  <enum name='model'><value>tpm-tis</value><value>tpm-crb</value></enum>
  <enum name='backendModel'><value>emulator</value><value>external</value></enum>
  <enum name='backendVersion'><value>2.0</value></enum>
</tpm></devices></domainCapabilities>"""

# Secure Boot firmware without Microsoft's keys, and no swtpm
BARE = """<domainCapabilities><os supported='yes'>
  <enum name='firmware'><value>efi</value></enum>
  <firmwareFeatures supported='yes'>
    <enum name='secureBoot'><value>yes</value><value>no</value></enum>
    <enum name='enrolledKeys'><value>no</value></enum>
  </firmwareFeatures>
</os><devices><tpm supported='no'/></devices></domainCapabilities>"""

# only Secure Boot firmware, and a TPM of another machine
SECURE_ONLY = """<domainCapabilities><os supported='yes'>
  <enum name='firmware'><value>efi</value></enum>
  <firmwareFeatures supported='yes'>
    <enum name='secureBoot'><value>yes</value></enum>
    <enum name='enrolledKeys'><value>yes</value></enum>
  </firmwareFeatures>
</os><devices><tpm supported='yes'>
  <enum name='model'><value>tpm-spapr</value></enum>
  <enum name='backendModel'><value>emulator</value></enum>
  <enum name='backendVersion'><value>2.0</value></enum>
</tpm></devices></domainCapabilities>"""

# libvirt before 12.1: no firmwareFeatures, the loaders say whether they do Secure Boot
EARLIER = """<domainCapabilities><os supported='yes'>
  <enum name='firmware'><value>efi</value></enum>
  <loader supported='yes'><enum name='secure'><value>yes</value><value>no</value></enum></loader>
</os></domainCapabilities>"""
EARLIER_PLAIN = """<domainCapabilities><os supported='yes'>
  <enum name='firmware'><value>efi</value></enum>
  <loader supported='yes'/>
</os></domainCapabilities>"""

DOM_CAPS = {"domain": "kvm", "os_support": "yes", "cpu_modes": ["host-model"]}


def host(dom_cap_xml):
    conn = wvmConnect.__new__(wvmConnect)
    conn.get_dom_cap_xml = lambda arch, machine: dom_cap_xml
    return conn


def defined(firmware, tpm_model=None):
    conn = wvmCreate.__new__(wvmCreate)
    conn.wvm = MagicMock()
    with patch.object(wvmCreate, "get_capabilities", return_value={"features": ["acpi"], "os_type": "hvm"}), \
            patch.object(wvmCreate, "get_dom_capabilities", return_value=DOM_CAPS):
        conn.create_instance(name="vm-1", memory=512, vcpu=1, vcpu_mode="host-model",
                             uuid="00000000-0000-4000-8000-0000000000c2", arch="x86_64", machine="q35",
                             firmware=firmware, volumes=[], networks="", nwfilter="", virtio=True,
                             listener_addr="0.0.0.0", add_cdrom="None", add_input="None", tpm_model=tpm_model)
    return etree.fromstring(conn.wvm.defineXML.call_args.args[0])


class HostOffersTests(SimpleTestCase):
    def test_a_host_with_enrolled_keys_and_swtpm_offers_everything(self):
        self.assertEqual(host(FULL).get_firmwares("x86_64", "q35"), ["BIOS", "UEFI", "UEFI Secure Boot"])
        self.assertEqual(host(FULL).get_tpm_model("x86_64", "q35"), "tpm-crb")

    def test_secure_boot_without_microsofts_keys_and_no_swtpm_are_not_offered(self):
        self.assertEqual(host(BARE).get_firmwares("x86_64", "q35"), ["BIOS", "UEFI"])
        self.assertIsNone(host(BARE).get_tpm_model("x86_64", "q35"))

    def test_bios_is_x86_only_and_secure_boot_x86_64_only(self):
        self.assertEqual(host(FULL).get_firmwares("aarch64", "virt"), ["UEFI"])

    def test_uefi_is_offered_only_where_secure_boot_can_be_off(self):
        self.assertEqual(host(SECURE_ONLY).get_firmwares("x86_64", "q35"), ["BIOS", "UEFI Secure Boot"])

    def test_an_earlier_libvirt_offers_what_its_loaders_do(self):
        self.assertEqual(host(EARLIER).get_firmwares("x86_64", "q35"), ["BIOS", "UEFI", "UEFI Secure Boot"])
        self.assertEqual(host(EARLIER_PLAIN).get_firmwares("x86_64", "q35"), ["BIOS", "UEFI"])

    def test_a_machine_without_crb_or_tis_takes_its_own_tpm_model(self):
        self.assertEqual(host(SECURE_ONLY).get_tpm_model("ppc64le", "pseries"), "tpm-spapr")


class DefinitionTests(SimpleTestCase):
    def features(self, tree):
        return {f.get("name"): f.get("enabled") for f in tree.findall("os/firmware/feature")}

    def test_bios_leaves_the_firmware_to_the_machine(self):
        tree = defined("BIOS")
        self.assertIsNone(tree.find("os").get("firmware"))
        self.assertEqual((self.features(tree), tree.find("features/smm")), ({}, None))

    def test_uefi_is_picked_by_libvirt_without_secure_boot(self):
        tree = defined("UEFI")
        self.assertEqual(tree.find("os").get("firmware"), "efi")
        self.assertEqual(self.features(tree), {"secure-boot": "no"})
        self.assertIsNone(tree.find("features/smm"))

    def test_secure_boot_has_microsofts_keys_and_smm(self):
        tree = defined("UEFI Secure Boot")
        self.assertEqual(tree.find("os").get("firmware"), "efi")
        self.assertEqual(self.features(tree), {"secure-boot": "yes", "enrolled-keys": "yes"})
        self.assertEqual(tree.find("features/smm").get("state"), "on")

    def test_a_tpm_is_an_emulated_tpm_2(self):
        self.assertEqual(defined("UEFI").findall("devices/tpm"), [])
        tpm = defined("UEFI Secure Boot", tpm_model="tpm-crb").find("devices/tpm")
        self.assertEqual((tpm.get("model"), tpm.find("backend").get("type"), tpm.find("backend").get("version")),
                         ("tpm-crb", "emulator", "2.0"))
