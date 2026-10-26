"""The VM API answers as its web pages do: a template is not started, the
host's ISO images are a superuser's, flavors and migrations take what the
web forms take."""

from unittest.mock import patch

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
