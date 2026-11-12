"""The VM API answers as its web pages do: a template is not started, the
host's ISO images are a superuser's, flavors and migrations take what the
web forms take."""

from unittest.mock import patch

import libvirt

from accounts.models import UserInstance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from instances.api.serializers import InstanceDetailsSerializer, MigrateSerializer
from instances.models import Flavor, Instance


class ApiParityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("api-owner", password="pw")
        self.admin = get_user_model().objects.create_superuser("api-admin", "api@example.com", "pw")
        self.compute = Compute.objects.create(name="api-host", hostname="192.0.2.30", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=self.compute, name="api-vm", uuid="31313131-0000-0000-0000-000000000000",
                                          is_template=True)
        UserInstance.objects.create(user=self.user, instance=self.vm)
        self.url = f"/api/v1/computes/{self.compute.id}/instances/{self.vm.id}/"

    def test_a_json_body_starts_a_vm_without_its_saved_state(self):
        Instance.objects.filter(pk=self.vm.pk).update(is_template=False)
        self.client.force_login(self.user)
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.get_status.return_value = 5
            response = self.client.post(self.url + "poweron/", {"fresh": True}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        wvm.return_value.start.assert_called_once_with(libvirt.VIR_DOMAIN_START_FORCE_BOOT)

    def test_a_template_is_not_started(self):
        self.client.force_login(self.user)
        with patch("instances.models.wvmInstance") as wvm:
            for action in ("poweron", "powercycle"):
                with self.subTest(action=action):
                    self.assertEqual(self.client.post(self.url + f"{action}/").status_code, 409)
        wvm.return_value.start.assert_not_called()

    def test_the_hosts_iso_images_are_a_superusers(self):
        class Request:
            def __init__(self, user):
                self.user = user

        for user, shown in ((self.user, False), (self.admin, True)):
            fields = InstanceDetailsSerializer(self.vm, context={"request": Request(user)}).fields
            self.assertEqual("media_iso" in fields, shown, user)

    def test_the_hosts_files_and_pools_are_a_superusers(self):
        # the VM page shows an owner none of them: a disk is its device, size and settings
        class Request:
            def __init__(self, user):
                self.user = user

        read = {"disks": [{"dev": "vda", "size": 1, "image": "a.qcow2", "storage": "default", "path": "/pool/a.qcow2",
                           "backing_file": "/pool/base.qcow2"}],
                "media": [{"dev": "sda", "image": "x.iso", "storage": "iso", "path": "/iso/x.iso"}],
                "firmware": {"loader": "/usr/share/OVMF/OVMF_CODE.fd", "type": "pflash"},
                "snapshots": [{"name": "s", "detaches": [{"dev": "vdb", "path": "/pool/b.qcow2"}]}, {"name": "i"}]}
        with patch("rest_framework.serializers.ModelSerializer.to_representation", return_value=read):
            owner = InstanceDetailsSerializer(self.vm, context={"request": Request(self.user)}).data
            admin = InstanceDetailsSerializer(self.vm, context={"request": Request(self.admin)}).data
        self.assertEqual(owner, {"disks": [{"dev": "vda", "size": 1}], "media": [{"dev": "sda"}], "firmware": {"type": "pflash"},
                                 "snapshots": [{"name": "s", "detaches": [{"dev": "vdb"}]}, {"name": "i", "detaches": []}]})
        self.assertEqual(admin, read)
        self.assertNotIn("nvram", InstanceDetailsSerializer(self.vm, context={"request": Request(self.user)}).fields)

    def test_a_flavor_is_at_least_one_of_each_and_has_its_id(self):
        self.client.force_login(self.admin)
        response = self.client.post("/api/v1/flavor/", {"label": "zero", "memory": 0, "vcpu": -1, "disk": 0},
                                    content_type="application/json")
        self.assertEqual(set(response.json()), {"memory", "vcpu", "disk"})
        flavor = Flavor.objects.create(label="one", memory=1024, vcpu=1, disk=10)
        self.assertEqual(self.client.get(f"/api/v1/flavor/{flavor.id}/").json()["id"], flavor.id)

    def test_a_migration_needs_neither_live_nor_offline(self):
        other = Compute.objects.create(name="api-host-2", hostname="192.0.2.31", login="u", password="p", type=1)
        data = {"instance": self.vm.id, "target_compute": other.id, "submission_key": "k" * 12}
        serializer = MigrateSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual((serializer.validated_data["live"], serializer.validated_data["offline"]), (True, False))

    def test_a_vm_on_an_unknown_compute_is_not_found(self):
        from django.http import Http404
        from instances.jobs import CreateInstance

        with self.assertRaises(Http404):
            CreateInstance().validate(self.admin, {"compute": 999999})
