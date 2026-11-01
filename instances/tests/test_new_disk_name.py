"""A new disk or CD-ROM gets a name neither definition uses: on an active
VM a disk can be pending in the persistent definition only, or still in the
running VM only, and the attach goes to both."""

from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance


def dev(name, bus):
    return {"dev": name, "bus": bus, "image": f"{name}.qcow2", "storage": "default", "path": f"/pool/{name}.qcow2",
            "format": "qcow2", "size": 1 << 30}


class NewDiskNameTestCase(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("nd-admin", "nd@example.com", "x"))
        compute = Compute.objects.create(name="nd", hostname="127.0.0.1:1", login="root", password="", type=1)
        self.instance = Instance.objects.create(compute=compute, name="nd-vm", uuid="aaaaaaaa-5555-2222-3333-444444444444")

    def attach(self, view, data, live=((), ()), config=((), ()), status=1):
        """The attach_disk call of view; live and config are (disks, media) of each definition."""
        with patch("instances.models.wvmInstance") as wvm, patch("instances.views.wvmStorage") as storage, patch(
            "instances.views.wvmCreate"
        ) as create:
            proxy = wvm.return_value
            proxy.get_disk_devices.side_effect = lambda **kw: list((config if kw.get("config") else live)[0])
            proxy.get_media_devices.side_effect = lambda **kw: list((config if kw.get("config") else live)[1])
            proxy.get_disk_bus_types.return_value = ["virtio", "sata", "scsi", "usb"]
            proxy.get_iso_path.side_effect = lambda image: f"/iso/{image}"
            proxy.get_cache_modes.return_value = {"default": "", "none": ""}
            proxy.get_machine_type.return_value = "q35"
            proxy.get_status.return_value = status
            storage.return_value.get_volumes.return_value = ["data.qcow2"]
            storage.return_value.get_type.return_value = "dir"
            storage.return_value.get_volume_type.return_value = "file"
            storage.return_value.get_volume_format_type.return_value = "qcow2"
            create.return_value.create_volume.return_value = "/pool/data.qcow2"
            self.response = self.client.post(reverse(f"instances:{view}", args=[self.instance.id]), data, follow=True)
        self.proxy = proxy
        return proxy.attach_disk.call_args

    VIEWS = (
        ("add_new_vol", {"storage": "default", "name": "data", "format": "qcow2", "size": "1", "cache": "default"}, 1),
        ("add_existing_vol", {"selected_storage": "default", "vols": "data.qcow2", "cache": "default"}, 1),
        ("add_cdrom", {}, 5),  # shut off: a running VM takes USB and SCSI CD-ROMs only
    )

    def test_a_name_either_definition_uses_is_not_given_again(self):
        vda = dev("vda", "virtio")
        cases = (
            # bus, live (disks, media), persistent (disks, media), expected name
            ("scsi", ([vda], []), ([vda, dev("sda", "sata")], []), "sdb"),  # pending sata rename; scsi shares sd
            ("sata", ([vda], []), ([vda], [dev("sda", "sata")]), "sdb"),  # pending CD-ROM
            ("virtio", ([vda, dev("vdb", "virtio")], []), ([vda], []), "vdc"),  # not yet released by the guest
            ("virtio", ([vda], []), ([vda], []), "vdb"),  # both the same, as on a stopped VM
        )
        for view, data, status in self.VIEWS:
            for bus, live, config, expected in cases:
                if view == "add_cdrom" and bus == "virtio":  # no virtio CD-ROM
                    continue
                with self.subTest(view=view, bus=bus, expected=expected):
                    call = self.attach(view, {**data, "bus": bus}, live, config, status=status)
                    self.assertEqual(call.args[0], expected)

    def test_a_cdrom_of_a_running_vm_is_on_a_bus_that_can_be_hotplugged(self):
        # running, paused: USB first, which every guest sees; shut off: SATA
        for status, bus in ((1, "usb"), (3, "usb"), (5, "sata")):
            with self.subTest(status=status):
                call = self.attach("add_cdrom", {"media": "virtio-win.iso"}, status=status)
                self.assertEqual((call.kwargs["target_bus"], call.args[1]), (bus, "/iso/virtio-win.iso"))

    def test_a_running_vm_refuses_a_sata_cdrom_and_a_usb_one_without_media(self):
        for data in ({"bus": "sata", "media": "virtio-win.iso"}, {"bus": "usb", "media": ""}):
            with self.subTest(data):
                self.attach("add_cdrom", data, status=1)
                self.proxy.attach_disk.assert_not_called()
                self.assertTrue(list(self.response.context["messages"]))

    def test_a_cdrom_without_media_is_empty(self):
        call = self.attach("add_cdrom", {"bus": "scsi", "media": ""}, status=1)
        self.assertEqual((call.kwargs["target_bus"], call.args[1]), ("scsi", ""))
