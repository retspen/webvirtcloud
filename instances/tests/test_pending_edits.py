"""On an active VM an edit changes the persistent definition and is pending
until the next start. The edit forms show that definition, so a save does
not post the running VM's value back over a pending change."""

from unittest.mock import PropertyMock, patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import html
from vrtManager import util


def disk(dev, cache, serial):
    return {
        "dev": dev, "bus": "virtio", "image": f"{dev}.qcow2", "storage": "default", "path": f"/pool/{dev}.qcow2",
        "format": "qcow2", "backing_file": None, "size": 1 << 30, "used": 1 << 20, "cache": cache, "io": "default",
        "discard": "default", "detect_zeroes": "default", "readonly": False, "shareable": False, "serial": serial,
    }


class PendingEditsTestCase(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("pe-admin", "pe@example.com", "x"))
        compute = Compute.objects.create(name="pe", hostname="127.0.0.1:1", login="root", password="", type=1)
        self.instance = Instance.objects.create(compute=compute, name="pe-vm", uuid="aaaaaaaa-1111-2222-3333-444444444444")

    def page(self, live=(), config=(), qos=({}, {}), status=1, **getters):
        """live and config: disks; qos and getters (get_vcpu=(2, 4)): values of
        the live and the persistent definition."""
        with patch("instances.models.wvmInstance") as wvm, patch.object(
            Compute, "status", new_callable=PropertyMock, return_value=True
        ):
            proxy = wvm.return_value
            proxy.get_status.return_value = status
            proxy.get_memory.return_value = proxy.get_cur_memory.return_value = 1024
            proxy.get_max_memory.return_value = 4096
            getters = {"get_vcpu": (1, 1), "get_cur_vcpu": (1, 1), "get_title": ("", ""),
                       "get_description": ("", ""), **getters}
            for getter, values in getters.items():
                getattr(proxy, getter).side_effect = lambda config=False, values=values: values[config]
            proxy.get_max_cpus.return_value = [1, 2, 3, 4]
            proxy.get_vcpus.return_value = {}
            for getter in ("get_networks", "get_ifaces", "get_storages", "get_media_devices", "get_net_devices",
                           "get_snapshot", "get_snapshot_jobs"):
                getattr(proxy, getter).return_value = []
            proxy.get_hostdevs.return_value = ([], [], [])
            proxy.get_disk_devices.side_effect = lambda **kw: config if kw.get("config") else live
            proxy.get_all_qos.side_effect = lambda **kw: qos[1] if kw.get("config") else qos[0]
            proxy.get_console_type.return_value = "vnc"
            proxy.get_video_models.return_value = ["vga", "virtio"]
            proxy.get_cache_modes.return_value = {"default": "Default", "none": "Disabled"}
            response = self.client.get(reverse("instances:instance", args=[self.instance.id]))
        self.assertEqual(response.status_code, 200)
        return html.fromstring(response.content)

    def test_the_disk_edit_form_shows_the_pending_definition(self):
        # running: cache=none and a new disk vdb pending, vda's serial live only
        doc = self.page(
            live=[disk("vda", "default", "live-serial")],
            config=[disk("vda", "none", ""), disk("vdb", "default", "")],
        )
        forms = doc.xpath("//form[@action=$a]", a=reverse("instances:edit_volume", args=[self.instance.id]))
        self.assertEqual([f.xpath("string(.//input[@name='dev']/@value)") for f in forms], ["vda", "vdb"])
        vda = forms[0]
        self.assertEqual(vda.xpath(".//select[@name='vol_cache']/option[@selected]/@value"), ["none"])
        self.assertEqual(vda.xpath("string(.//input[@name='vol_serial']/@value)"), "")

    def test_the_qos_form_shows_the_pending_definition(self):
        mac = "52:54:10:00:00:01"
        inbound = {"direction": "inbound", "average": "500", "peak": "0", "burst": "0", "floor": None}
        doc = self.page(qos=({mac: [inbound]}, {mac: [{**inbound, "average": "1000"}, {**inbound, "direction": "outbound"}]}))
        self.assertEqual(doc.xpath("//input[@name='qos_average']/@value"), ["1000", "500"])
        # the pending outbound has a row
        self.assertEqual([" ".join(t.split()) for t in doc.xpath("//label[@class='col-form-label']/text()")],
                         [f"{mac} Inbound", f"{mac} Outbound"])

    def test_one_disk_card_spans_the_row_and_more_sit_side_by_side(self):
        for disks, wide in (([disk("vda", "default", "")], ["col-12"]),
                            ([disk("vda", "default", ""), disk("vdb", "default", "")], ["col-12 col-md-6"] * 2)):
            with self.subTest(count=len(disks)):
                doc = self.page(live=disks, config=disks)
                self.assertEqual(doc.xpath("//div[@id='disks']//div[article[starts-with(@aria-labelledby, 'disk-')]]/@class"),
                                 wide)

    def test_a_disk_with_a_pending_source_is_not_deleted(self):
        # running: vda is A, its definition for the next start uses B
        with patch("instances.models.wvmInstance") as wvm, patch("instances.views.wvmStorage") as storage:
            proxy = wvm.return_value
            live, pending = disk("vda", "default", ""), {**disk("vda", "default", ""), "path": "/pool/b.qcow2"}
            proxy.get_disk_devices.side_effect = lambda **kw: [pending] if kw.get("config") else [live]
            self.client.post(reverse("instances:delete_vol", args=[self.instance.id]), {"dev": "vda"})
        proxy.detach_disk.assert_not_called()
        storage.return_value.del_volume.assert_not_called()

    def test_the_options_and_cpu_forms_show_the_pending_definition(self):
        doc = self.page(get_vcpu=(2, 4), get_cur_vcpu=(1, 3), get_title=("old", "new"),
                        get_description=("live text", "pending text"))
        self.assertEqual(doc.xpath("//input[@name='title']/@value"), ["new"])
        self.assertEqual(doc.xpath("//textarea[@name='description']/text()"), ["pending text"])
        self.assertEqual(doc.xpath("//select[@name='vcpu']/option[@selected]/@value"), ["4"])
        self.assertEqual(doc.xpath("//select[@name='cur_vcpu']/option[@selected]/@value"), ["3"])

    def test_buttons_shown_as_disabled_cannot_submit(self):
        # running: the CPU, options and video forms wait for a shutdown
        doc = self.page(live=[disk("vda", "default", "")], config=[disk("vda", "default", "")])
        self.assertGreater(len(doc.xpath("//button[@disabled]")), 5)
        shown = doc.xpath("//button[contains(concat(' ', @class, ' '), ' disabled ')]")
        self.assertEqual([b for b in shown if b.get("disabled") is None], [])
        for action in ("resizevm_cpu", "change_options", "set_video_model", "detach_vol", "delete_vol"):
            with self.subTest(action):
                (form,) = doc.xpath("//form[@action=$a]", a=reverse(f"instances:{action}", args=[self.instance.id]))
                self.assertTrue(all(b.get("disabled") is not None for b in form.xpath(".//button")))

    def test_the_xml_editor_shows_the_definition_for_the_next_start(self):
        # static/js/xml_editor.js opens the review dialog on Change, also while the VM runs
        for status in (5, 1):
            with self.subTest(status=status):
                doc = self.page(status=status)
                (button,) = doc.xpath("//form[@id='xml-form']//button[@type='submit']")
                self.assertIsNone(button.get("disabled"))
                self.assertEqual(len(doc.xpath("//div[@id='xml-review']//button[@id='xml-review-save']")), 1)
                self.assertEqual(bool(doc.xpath("//p[@id='xml-next-start']")), status != 5)

    def test_the_boot_video_and_console_forms_show_the_pending_definition(self):
        cd = {"dev": "sda", "image": "pending.iso", "storage": "default", "path": "/pool/pending.iso", "bus": "sata"}
        with patch("instances.models.Instance.config_networks", new_callable=PropertyMock, return_value=[]):
            doc = self.page(
                live=[disk("vda", "default", "")], config=[disk("vda", "default", ""), disk("vdb", "default", "")],
                get_bootmenu=(False, True), get_bootorder=({}, {0: {"type": "file", "dev": "cdrom", "target": "sda"}}),
                get_media_devices=([], [cd]), get_video_model=("vga", "virtio"),
                get_console_listener_addr=("127.0.0.1", "0.0.0.0"), get_console_keymap=("", "de"),
                get_console_passwd=("live-pw", "pending-pw"),
            )
        (boot,) = doc.xpath("//form[@action=$a]", a=reverse("instances:set_bootorder", args=[self.instance.id]))
        self.assertEqual(boot.xpath(".//input[@type='checkbox']/@value"), ["disk:vda", "disk:vdb", "cdrom:sda"])
        self.assertIn("1:sda", doc.xpath("string(//div[label[contains(., ':')]])"))
        self.assertEqual(doc.xpath("//select[@name='video_model']/option[@selected]/@value"), ["virtio"])
        self.assertEqual(doc.xpath("//select[@name='keymap']/option[@selected]/@value"), ["de"])
        self.assertEqual(doc.xpath("//select[@name='listen_on']/option[@selected]/@value"), ["0.0.0.0"])
        self.assertEqual(doc.xpath("//input[@name='password']/@value"), ["pending-pw"])

    def test_a_boot_order_choice_not_in_the_definition_is_refused(self):
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.set_bootorder.side_effect = util.OperationError("Boot device vdz is not in the definition")
            response = self.client.post(reverse("instances:set_bootorder", args=[self.instance.id]),
                                        {"bootorder": "disk:vda,disk:vdz"})
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], ["Boot device vdz is not in the definition"])

    def test_an_active_vm_says_its_settings_apply_at_the_next_start(self):
        for status, shown in ((1, True), (3, True), (5, False)):
            with self.subTest(status=status):
                self.assertEqual(bool(self.page(status=status).xpath("//p[@id='next-start-note']")), shown)
