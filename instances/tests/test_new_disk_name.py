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
            proxy.get_disk_bus_types.return_value = ["virtio", "sata", "scsi"]
            proxy.get_cache_modes.return_value = {"default": "", "none": ""}
            proxy.get_machine_type.return_value = "q35"
            proxy.get_status.return_value = status
            storage.return_value.get_volumes.return_value = ["data.qcow2"]
            storage.return_value.get_type.return_value = "dir"
            storage.return_value.get_volume_type.return_value = "file"
            storage.return_value.get_volume_format_type.return_value = "qcow2"
            create.return_value.create_volume.return_value = "/pool/data.qcow2"
            self.client.post(reverse(f"instances:{view}", args=[self.instance.id]), data)
        proxy.attach_disk.assert_called_once()
        return proxy.attach_disk.call_args

    VIEWS = (
        ("add_new_vol", {"storage": "default", "name": "data", "format": "qcow2", "size": "1", "cache": "default"}),
        ("add_existing_vol", {"selected_storage": "default", "vols": "data.qcow2", "cache": "default"}),
        ("add_cdrom", {}),
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
        for view, data in self.VIEWS:
            for bus, live, config, expected in cases:
                with self.subTest(view=view, bus=bus, expected=expected):
                    self.assertEqual(self.attach(view, {**data, "bus": bus}, live, config).args[0], expected)

    def test_a_cdrom_of_a_running_vm_is_on_the_bus_that_can_be_hotplugged(self):
        for status, bus in ((1, "scsi"), (3, "scsi"), (5, "sata")):  # running, paused, shut off
            with self.subTest(status=status):
                self.assertEqual(self.attach("add_cdrom", {}, status=status).kwargs["target_bus"], bus)
