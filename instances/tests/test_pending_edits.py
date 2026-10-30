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

    def page(self, live=(), config=(), nics=((), ()), status=1, **getters):
        """live and config: disks; nics and getters (get_vcpu=(2, 4)): values of
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
            for getter in ("get_networks", "get_ifaces", "get_storages", "get_media_devices",
                           "get_snapshot", "get_snapshot_jobs"):
                getattr(proxy, getter).return_value = []
            proxy.get_hostdevs.return_value = ([], [], [])
            proxy.get_disk_devices.side_effect = lambda **kw: config if kw.get("config") else live
            proxy.get_net_devices.side_effect = lambda config=False: [dict(nic) for nic in nics[config]]
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
        nic = {"type": "network", "mac": "52:54:10:00:00:01", "nic": "default", "state": "up", "model": "virtio",
               "ipv4": None, "ipv6": None, "filterref": "", "target": "vnet0", "outbound": [],
               "inbound": {"average": "500", "peak": "0", "burst": "0"}}
        pending = {**nic, "inbound": {"average": "1000", "peak": "0", "burst": "0"}, "outbound": nic["inbound"]}
        doc = self.page(nics=([nic], [pending]))
        # the pending inbound value, and the pending outbound limit has a form
        self.assertEqual(doc.xpath("//input[@name='qos_average']/@value"), ["1000", "500"])
        self.assertEqual(doc.xpath("//form[.//input[@name='qos_average']]//input[@name='qos_direction']/@value"),
                         ["inbound", "outbound"])

    def test_one_nic_card_spans_the_row_and_more_sit_side_by_side(self):
        nic = {"type": "network", "mac": "52:54:10:00:00:01", "nic": "default", "state": "up", "model": "virtio",
               "ipv4": None, "ipv6": None, "filterref": "", "target": "", "inbound": [], "outbound": []}
        second = {**nic, "mac": "52:54:10:00:00:02"}
        for nics, wide in (([nic], ["col-12"]), ([nic, second], ["col-12 col-md-6"] * 2)):
            with self.subTest(count=len(nics)):
                doc = self.page(nics=(nics, nics))
                self.assertEqual(doc.xpath("//div[@id='network']//div[article]/@class"), wide)

    def test_one_disk_card_spans_the_row_and_more_sit_side_by_side(self):
        for disks, wide in (([disk("vda", "default", "")], ["col-12"]),
                            ([disk("vda", "default", ""), disk("vdb", "default", "")], ["col-12 col-md-6"] * 2)):
            with self.subTest(count=len(disks)):
                doc = self.page(live=disks, config=disks)
                self.assertEqual(doc.xpath("//div[@id='disks']//div[article[starts-with(@aria-labelledby, 'disk-')]]/@class"),
                                 wide)

    def test_the_clone_form_lists_the_persistent_devices(self):
        nic = {"type": "network", "mac": "52:54:10:00:00:01", "nic": "default", "state": "up", "model": "virtio",
               "ipv4": None, "ipv6": None, "filterref": "", "target": "", "inbound": [], "outbound": []}
        nics = [nic, {**nic, "mac": "52:54:10:00:00:02"}]
        for status, metadata in ((1, []), (5, ["meta-vda", "meta-vdb"])):
            with self.subTest(status=status):
                # running: vdb is pending the next start
                doc = self.page(live=[disk("vda", "default", "")], config=[disk("vda", "default", ""), disk("vdb", "default", "")],
                                nics=([nic], nics), status=status)
                (form,) = doc.xpath("//form[@action=$a]", a=reverse("instances:clone", args=[self.instance.id]))
                self.assertEqual(form.xpath(".//input[@type='text']/@name"),
                                 ["name", "clone-net-mac-0", "clone-net-mac-1", "disk-vda", "disk-vdb", "clone-title"])
                # the DHCP entry of the clone's name holds one address: only the first NIC guesses it
                self.assertEqual(len(form.xpath(".//button[contains(@onclick, 'guess_mac_address')]")), 1)
                # a running or paused VM is copied by a backup, which does not preallocate
                self.assertEqual(form.xpath(".//input[@type='checkbox']/@name"), metadata)

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

    def test_the_agent_and_vcpu_hot_plug_forms_show_the_pending_definition(self):
        # running without an agent channel and hot plug, both pending for the next start
        hotplug = {"0": {"enabled": "yes", "hotpluggable": "no", "order": "1"},
                   "1": {"enabled": "yes", "hotpluggable": "yes", "order": "2"}}
        doc = self.page(get_guest_agent=(None, object()), get_vcpus=({}, hotplug))
        self.assertEqual(doc.xpath("//select[@name='guest_agent']/option[@selected]/@value"), ["True"])
        self.assertEqual(doc.xpath("//select[@name='vcpu_hotplug']/option[@selected]/@value"), ["True"])
        self.assertIn("No channel", doc.xpath("string(//form[.//select[@name='guest_agent']])"))

    def test_a_custom_rng_or_crash_action_is_left_to_the_xml_editor(self):
        doc = self.page(get_rng=("custom", "custom"), get_on_crash=("preserve", "preserve"))
        self.assertIsNotNone(doc.xpath("//input[@name='rng']")[0].get("disabled"))
        self.assertEqual(doc.xpath("//select[@name='on_crash']"), [])
        self.assertIn("preserve: change it in the XML editor.", doc.xpath("string(//p[@id='on_crash'])"))
        doc = self.page(get_rng=("virtio", "virtio"), get_on_crash=("restart", "restart"))  # read from the persistent definition
        self.assertEqual(doc.xpath("//input[@name='rng']/@checked"), ["checked"])
        self.assertEqual(doc.xpath("//select[@name='on_crash']/option[@selected]/@value"), ["restart"])

    def test_buttons_shown_as_disabled_cannot_submit(self):
        # running: the CPU resize, vCPU hot plug, template and disk removal forms wait for a shutdown;
        # the title, description and video model are of the next start, saved at once
        doc = self.page(live=[disk("vda", "default", "")], config=[disk("vda", "default", "")])
        self.assertGreater(len(doc.xpath("//button[@disabled]")), 4)
        shown = doc.xpath("//button[contains(concat(' ', @class, ' '), ' disabled ')]")
        self.assertEqual([b for b in shown if b.get("disabled") is None], [])
        for action, waits in (("resizevm_cpu", True), ("set_vcpu_hotplug", True), ("set_template", True),
                              ("detach_vol", True), ("delete_vol", True),
                              ("change_options", False), ("set_video_model", False)):
            with self.subTest(action):
                (form,) = doc.xpath("//form[@action=$a]", a=reverse(f"instances:{action}", args=[self.instance.id]))
                controls = form.xpath(".//button | .//input[@type='checkbox']")
                self.assertEqual([c.get("disabled") is not None for c in controls], [waits] * len(controls))

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
        # the devices in the order first, checked
        self.assertEqual(boot.xpath(".//input[@type='checkbox']/@value"), ["cdrom:sda", "disk:vda", "disk:vdb"])
        self.assertEqual(boot.xpath(".//input[@checked]/@value"), ["cdrom:sda"])
        # the pending boot menu is on: its switch turns it off, also while the VM runs
        self.assertEqual(doc.xpath("//input[@id='bootmenu']/ancestor::form/@action"),
                         [reverse("instances:unset_bootmenu", args=[self.instance.id])])
        self.assertEqual(doc.xpath("//select[@name='video_model']/option[@selected]/@value"), ["virtio"])
        self.assertEqual(doc.xpath("//select[@name='keymap']/option[@selected]/@value"), ["de"])
        self.assertEqual(doc.xpath("//select[@name='listen_on']/option[@selected]/@value"), ["0.0.0.0"])
        # the pending password is not shown, only that one is set
        self.assertEqual(doc.xpath("//input[@name='password']/@value"), [])
        self.assertIn("A password is set.", doc.xpath("string(//div[@id='vncsettings']//fieldset)"))

    def test_a_boot_order_by_device_type_is_named_and_no_device_is_checked(self):
        doc = self.page(live=[disk("vda", "default", "")], config=[disk("vda", "default", "")],
                        get_bootorder=({}, {0: {"type": "file", "dev": "hd", "target": "disk"},
                                            1: {"type": "file", "dev": "cdrom", "target": "cdrom"}}))
        self.assertIn("disk, cdrom.", " ".join(doc.xpath("string(//p[@id='boot-by-type'])").split()))
        self.assertEqual(doc.xpath("//div[@id='b_order']//input[@checked]"), [])

    def test_a_boot_order_choice_not_in_the_definition_is_refused(self):
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.set_bootorder.side_effect = util.OperationError("Boot device vdz is not in the definition")
            response = self.client.post(reverse("instances:set_bootorder", args=[self.instance.id]),
                                        {"bootorder": "disk:vda,disk:vdz"})
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], ["Boot device vdz is not in the definition"])

    def test_an_empty_boot_order_is_refused(self):
        with patch("instances.models.wvmInstance") as wvm:
            response = self.client.post(reverse("instances:set_bootorder", args=[self.instance.id]), {"bootorder": ""})
        wvm.return_value.set_bootorder.assert_not_called()
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], ["Check at least one device to boot from."])

    def test_an_active_vm_says_its_settings_apply_at_the_next_start(self):
        for status, shown in ((1, True), (3, True), (5, False)):
            with self.subTest(status=status):
                self.assertEqual(bool(self.page(status=status).xpath("//p[@id='next-start-note']")), shown)
