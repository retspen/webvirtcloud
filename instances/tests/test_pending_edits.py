"""On an active VM an edit changes the persistent definition and is pending
until the next start. The edit forms show that definition, so a save does
not post the running VM's value back over a pending change."""

from unittest.mock import PropertyMock, patch
from urllib.parse import unquote

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

    def test_the_nics_are_rows_of_one_list_with_their_dialogs(self):
        nic = {"type": "network", "mac": "52:54:10:00:00:01", "nic": "default", "state": "up", "model": "virtio",
               "ipv4": None, "ipv6": None, "filterref": "", "target": "", "inbound": [], "outbound": []}
        nics = [nic, {**nic, "mac": "52:54:10:00:00:02"}]
        doc = self.page(nics=(nics, nics), get_networks=(["default", "isolated"],) * 2, get_ifaces=(["br0"],) * 2)
        rows = doc.xpath("//div[@id='network']//div[contains(@class, 'list-group')]/*")
        # nothing but the rows sits in the list: each row holds its Edit and Add QoS dialogs
        self.assertEqual([row.get("aria-labelledby") for row in rows], ["nic-0", "nic-1"])
        self.assertEqual([len(row.xpath(".//div[contains(@class, 'modal')][@id]")) for row in rows], [2, 2])
        # the Edit dialog picks the source by kind and posts it as before
        (source,) = doc.xpath("//select[@name='net-source-0']")
        self.assertEqual(source.xpath("./optgroup/@label"), ["Networks", "Interfaces"])
        self.assertEqual(source.xpath(".//option/@value"), ["", "net:default", "net:isolated", "iface:br0"])
        # the NIC keeps its source unless another is chosen
        self.assertEqual(source.xpath(".//option[@selected]/text()"), ["default, as it is"])
        self.assertEqual(doc.xpath("//div[@id='editInstanceNetwork0']//input[@name='net-old-mac-0']/@value"), [nic["mac"]])
        self.assertTrue(doc.xpath("//div[@id='editInstanceNetwork0']//button[@name='change_network']"))
        # so does one the host's lists do not show, or one whose name is in both
        doc = self.page(nics=([{**nic, "type": "bridge", "nic": "br0"}],) * 2,
                        get_networks=(["br0"],) * 2, get_ifaces=(["br0"],) * 2)
        (source,) = doc.xpath("//select[@name='net-source-0']")
        self.assertEqual(source.xpath(".//option[@selected]/@value"), [""])

    def test_the_disks_are_rows_of_one_list(self):
        disks = [disk("vda", "default", "") | {"used": 1 << 29}, disk("vdb", "default", "") | {"used": (1 << 30) + (1 << 20)}]
        doc = self.page(live=disks, config=disks)
        rows = doc.xpath("//div[@id='disks']//div[contains(@class, 'list-group')]/article[starts-with(@aria-labelledby, 'disk-')]")
        self.assertEqual([row.get("aria-labelledby") for row in rows], ["disk-vda", "disk-vdb"])
        # the used share as a bar, full when a qcow2 file outgrows its capacity
        self.assertEqual(doc.xpath("//div[@id='disks']//div[@role='progressbar']/@aria-valuenow"), ["50", "100"])

    def test_the_disk_edit_dialog_keeps_an_empty_serial_empty(self):
        disks = [disk("vda", "default", None)]
        doc = self.page(live=disks, config=disks)
        # saved untouched, the dialog must not give the disk the serial "None"
        self.assertEqual(doc.xpath("//div[@id='editvol0']//input[@name='vol_serial']/@value"), [""])
        # each switch's label toggles it
        for name in ("vol_readonly", "vol_shareable"):
            (switch,) = doc.xpath("//div[@id='editvol0']//input[@name=$n]", n=name)
            self.assertEqual(doc.xpath("//div[@id='editvol0']//label[@for=$i]", i=switch.get("id"))[0].tag, "label")

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

    def test_the_users_tab_shows_each_owner_and_offers_only_new_owners(self):
        from accounts.models import UserInstance

        User = get_user_model()
        owner = User.objects.create_user("pe-owner")
        UserInstance.objects.create(instance=self.instance, user=owner, is_change=True, is_vnc=True)
        User.objects.create_user("pe-new")
        User.objects.create_superuser("pe-admin2", "pe2@example.com", "x")
        doc = self.page()
        (row,) = doc.xpath("//div[@id='users']//li")
        self.assertIn("Change settings · Change console settings", " ".join(row.text_content().split()))
        # Remove and Edit rights come back to the Users tab
        self.assertEqual([unquote(href.split("?next=")[1]) for href in row.xpath(".//a[contains(@class, 'btn')]/@href")],
                         [f"/instances/{self.instance.id}/#users"] * 2)
        # not an owner yet and not an administrator, who can use every VM anyway
        self.assertEqual(doc.xpath("//select[@id='add-owner-user']/option/text()"), ["pe-new"])

    def test_a_paused_vm_offers_to_turn_vcpus_on_only(self):
        # unplugging a vCPU needs the guest, which a paused VM does not run
        vcpus = {"0": {"enabled": "yes", "hotpluggable": "no", "order": "1"},
                 "1": {"enabled": "yes", "hotpluggable": "yes", "order": "2"},
                 "2": {"enabled": "no", "hotpluggable": "yes", "order": "3"}}
        for status, off_disabled in ((1, False), (3, True)):
            with self.subTest(status=status):
                doc = self.page(status=status, get_vcpus=(vcpus, vcpus))
                buttons = {b.get("value"): b.get("disabled") is not None
                           for b in doc.xpath("//form[@action=$a]//button[@name='set_vcpu']",
                                              a=reverse("instances:set_vcpu", args=[self.instance.id]))}
                self.assertEqual(buttons, {"False": off_disabled, "True": False})

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
