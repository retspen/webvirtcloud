"""A disk's I/O limit (IOPS and MiB/s, reads and writes together; 0: none):
set by a superuser on the Disks tab, at once on a running VM and from its next start."""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import TestCase
from django.contrib.messages import get_messages
from libvirt import VIR_DOMAIN_AFFECT_CONFIG, VIR_DOMAIN_AFFECT_LIVE, VIR_DOMAIN_XML_INACTIVE, libvirtError

from accounts.models import UserInstance
from instances.models import Instance
from instances.tests import test_pending_edits
from instances.tests.test_pending_edits import disk
from logs.models import Logs
from vrtManager import util
from vrtManager.instance import wvmInstance


def limited(dev, iops=0, mibps=0):
    return {**disk(dev, "default", ""), "iops": iops, "mibps": mibps, "iotune_custom": False}


class DiskLimitTestCase(TestCase):
    setUp = test_pending_edits.PendingEditsTestCase.setUp
    page = test_pending_edits.PendingEditsTestCase.page  # the VM page with its host faked

    def post(self, data):
        with patch.object(Instance, "proxy", MagicMock()) as proxy:
            proxy.get_disk_devices.return_value = [limited("vda")]
            response = self.client.post(reverse("instances:set_disk_limit", args=[self.instance.id]),
                                        {"path": "/pool/vda.qcow2", **data})
        return response, proxy

    def test_a_superuser_sets_it_in_bytes(self):
        _response, proxy = self.post({"dev": "vda", "iops": "500", "mibps": "100"})
        proxy.set_disk_limit.assert_called_once_with("vda", 500, 100 * 2**20)
        self.assertEqual(Logs.objects.get(instance="pe-vm").message.split(": ")[-1], "disk vda I/O limit 500 IOPS, 100 MiB/s")

    def test_a_wrong_or_missing_value_is_refused(self):
        # a missing one would clear its limit; "²" is a digit to Python but not a number
        for data in ({"dev": "vda", "iops": "-1", "mibps": "0"}, {"dev": "vda", "iops": "x", "mibps": "0"},
                     {"dev": "vda", "iops": "²", "mibps": "0"}, {"dev": "vda", "iops": "1"},
                     {"dev": "vda", "iops": "0", "mibps": "1000001"}, {"dev": "vda", "iops": "9" * 5000, "mibps": "0"}):
            with self.subTest(data=data):
                response, proxy = self.post(data)
                proxy.set_disk_limit.assert_not_called()
                self.assertIn("whole numbers of IOPS and MiB/s", " ".join(map(str, get_messages(response.wsgi_request))))

    def test_what_libvirt_refuses_is_told(self):
        # the panel's own refusal and libvirt's: a message on the Disks tab, not an error page
        for error in (util.OperationError("The VM has a saved state: start it, then set the limit"),
                      libvirtError("unsupported configuration: block I/O throttling is not supported")):
            with self.subTest(error=error), patch.object(Instance, "proxy", MagicMock()) as proxy:
                self.client.cookies.pop("messages", None)  # each case's own message
                proxy.get_disk_devices.return_value = [limited("vda")]
                proxy.set_disk_limit.side_effect = error
                response = self.client.post(reverse("instances:set_disk_limit", args=[self.instance.id]),
                                            {"dev": "vda", "path": "/pool/vda.qcow2", "iops": "1", "mibps": "1"})
                self.assertRedirects(response, reverse("instances:instance", args=[self.instance.id]) + "#disks",
                                     fetch_redirect_response=False)
                self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], [str(error)])

    def test_a_disk_replaced_since_the_page_was_loaded_is_not_tuned(self):
        response, proxy = self.post({"dev": "vda", "path": "/pool/old.qcow2", "iops": "1", "mibps": "1"})
        proxy.set_disk_limit.assert_not_called()
        self.assertIn("has changed since the page was loaded", " ".join(map(str, get_messages(response.wsgi_request))))

    def test_an_owner_may_not(self):
        owner = get_user_model().objects.create_user("dl-owner", password="x")
        UserInstance.objects.create(instance=self.instance, user=owner, is_change=True)
        self.client.force_login(owner)
        response, proxy = self.post({"dev": "vda", "iops": "0", "mibps": "0"})
        self.assertEqual(response.status_code, 403)
        proxy.set_disk_limit.assert_not_called()

    def test_the_disk_tells_its_limit(self):
        doc = self.page(live=[limited("vda", 500, 100)], config=[limited("vda", 500, 100)])
        text = " ".join(doc.xpath("string(//article[@aria-labelledby='disk-vda'])").split())
        self.assertIn("I/O limit 500 IOPS, 100 MiB/s", text)
        (form,) = doc.xpath("//form[@action=$a]", a=reverse("instances:set_disk_limit", args=[self.instance.id]))
        self.assertEqual(form.xpath(".//input[@name='iops']/@value"), ["500"])
        self.assertEqual(form.xpath(".//input[@name='mibps']/@value"), ["100"])
        # tuning set in the XML, of the next start or of the running VM alone: no form
        custom = {**limited("vda"), "iotune_custom": True}
        for live, config in (([custom], [custom]), ([custom], [limited("vda")])):
            doc = self.page(live=live, config=config)
            self.assertIn("Set in the VM's XML", doc.text_content())
            self.assertFalse(doc.xpath("//form[@action=$a]", a=reverse("instances:set_disk_limit", args=[self.instance.id])))


def domain(*disks):
    return "<domain><devices>" + "".join(disks) + "</devices></domain>"


def disk_xml(dev="vda", source="/pool/vda.qcow2", iotune=""):
    return (f"<disk type='file' device='disk'><source file='{source}'/><target dev='{dev}' bus='virtio'/>"
            f"{f'<iotune>{iotune}</iotune>' if iotune else ''}</disk>")


class SetDiskLimitTestCase(TestCase):
    """The flags and refusals of wvmInstance.set_disk_limit, from the VM's two definitions."""

    def vm(self, live, config, active=1, persistent=1):
        vm = wvmInstance.__new__(wvmInstance)  # no connection: only these calls
        vm.instance = MagicMock(**{"isActive.return_value": active, "isPersistent.return_value": persistent,
                                   "hasManagedSaveImage.return_value": 0})
        vm.instance.XMLDesc.side_effect = lambda flags: config if flags & VIR_DOMAIN_XML_INACTIVE else live
        return vm

    def flags(self, vm):
        vm.set_disk_limit("vda", 500, 2**20)
        dev, params, flags = vm.instance.setBlockIoTune.call_args.args
        self.assertEqual((dev, params), ("vda", {"total_iops_sec": 500, "total_bytes_sec": 2**20}))
        return flags

    def test_each_definition_that_has_the_disk(self):
        both = domain(disk_xml())
        self.assertEqual(self.flags(self.vm(both, both)), VIR_DOMAIN_AFFECT_LIVE | VIR_DOMAIN_AFFECT_CONFIG)
        self.assertEqual(self.flags(self.vm(both, both, active=0)), VIR_DOMAIN_AFFECT_CONFIG)
        self.assertEqual(self.flags(self.vm(both, both, persistent=0)), VIR_DOMAIN_AFFECT_LIVE)  # transient
        self.assertEqual(self.flags(self.vm(domain(), both)), VIR_DOMAIN_AFFECT_CONFIG)  # attached for the next start
        # a running VM's source has more attributes: the same disk all the same
        running = domain(disk_xml().replace("<source file='/pool/vda.qcow2'/>", "<source file='/pool/vda.qcow2' index='1'/>"))
        self.assertEqual(self.flags(self.vm(running, both)), VIR_DOMAIN_AFFECT_LIVE | VIR_DOMAIN_AFFECT_CONFIG)

    def test_refused(self):
        for case, live, config, text in (
            ("no such disk", domain(), domain(), "no disk vda"),
            ("another disk at the next start", domain(disk_xml()), domain(disk_xml(source="/pool/new.qcow2")),
             "another disk from the next start"),
            ("a throttle group", domain(disk_xml(iotune="<total_iops_sec>5</total_iops_sec><group_name>db</group_name>")),
             domain(), "VM's XML"),
            ("a throttle filter", domain(), domain(disk_xml().replace(
                "</disk>", "<throttlefilters><throttlefilter group='db'/></throttlefilters></disk>")), "VM's XML"),
            ("past the form's range", domain(disk_xml(iotune="<total_iops_sec>10000001</total_iops_sec>")), domain(),
             "VM's XML"),
            ("another pool's volume of that name",
             domain("<disk type='volume' device='disk'><source pool='old' volume='root.qcow2'/><target dev='vda'/></disk>"),
             domain("<disk type='volume' device='disk'><source pool='new' volume='root.qcow2'/><target dev='vda'/></disk>"),
             "another disk from the next start"),
            ("a burst", domain(disk_xml(iotune="<total_iops_sec>5</total_iops_sec><total_iops_sec_max>9</total_iops_sec_max>")),
             domain(), "VM's XML"),
            ("read and write apart", domain(), domain(disk_xml(iotune="<read_iops_sec>5</read_iops_sec>")), "VM's XML"),
            ("not whole MiB/s", domain(disk_xml(iotune="<total_bytes_sec>524288</total_bytes_sec>")), domain(), "VM's XML"),
        ):
            with self.subTest(case):
                vm = self.vm(live, config)
                with self.assertRaisesRegex(util.OperationError, text):
                    vm.set_disk_limit("vda", 500, 2**20)
                vm.instance.setBlockIoTune.assert_not_called()

    def test_a_saved_state_is_resumed_first(self):
        # it would resume with the saved definition and its old limit
        vm = self.vm(domain(), domain(disk_xml()), active=0)
        vm.instance.hasManagedSaveImage.return_value = 1
        with self.assertRaisesRegex(util.OperationError, "saved state"):
            vm.set_disk_limit("vda", 500, 2**20)
        vm.instance.setBlockIoTune.assert_not_called()

    def test_the_disk_reads_its_limit(self):
        vm = self.vm(None, domain(disk_xml(iotune="<total_iops_sec>500</total_iops_sec><total_bytes_sec>104857600</total_bytes_sec>"
                                                  "<read_bytes_sec>0</read_bytes_sec>"),
                                  disk_xml("vdb", "/pool/vdb.qcow2", "<total_iops_sec>5</total_iops_sec><group_name>db</group_name>"), disk_xml("vdc", "/pool/vdc.qcow2")))
        with patch.object(wvmInstance, "_volume_details", return_value=None):
            disks = {d["dev"]: (d["iops"], d["mibps"], d["iotune_custom"]) for d in vm.get_disk_devices(config=True)}
        self.assertEqual(disks, {"vda": (500, 100, False), "vdb": (5, 0, True), "vdc": (0, 0, False)})
