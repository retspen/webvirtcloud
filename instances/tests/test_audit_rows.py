"""VM page owner changes and flavor changes write rows on the Logs page."""

from accounts.models import UserInstance
from appsettings.models import AppSettings
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from logs.models import Logs


def rows():
    return list(Logs.objects.order_by("id").values_list("message", "success"))


class VMOwnerRowTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("audit-admin", "audit@example.com", "pw"))
        self.bob = get_user_model().objects.create_user("bob")
        self.carol = get_user_model().objects.create_user("carol")
        compute = Compute.objects.create(name="c1", hostname="127.0.0.1", login="", password="", type=4)
        self.vm = Instance.objects.create(compute=compute, name="vm", uuid="77777777-7777-7777-7777-777777777777")
        Logs.objects.all().delete()  # the login's row

    def test_vm_page_owners(self):
        add = reverse("instances:add_owner", args=[self.vm.pk])
        self.client.post(add, {"user_id": self.bob.pk})
        self.client.post(add, {"user_id": self.bob.pk})  # already an owner: nothing changed
        AppSettings.objects.filter(key="ALLOW_INSTANCE_MULTIPLE_OWNER").update(value="False")
        self.client.post(add, {"user_id": self.carol.pk})
        self.assertFalse(UserInstance.objects.filter(user=self.carol).exists())
        ui = UserInstance.objects.get(user=self.bob)
        self.client.post(reverse("instances:del_owner", args=[self.vm.pk]), {"userinstance": ui.pk})
        self.assertEqual(rows(), [
            ("VM vm: add owner bob", True),
            ("VM vm: add owner carol: only one owner is allowed", False),
            ("VM vm: remove owner bob", True),
        ])
        shown = [log["message"] for log in self.client.get(reverse("vm_logs", args=[self.vm.pk])).json()]
        self.assertCountEqual(shown, [m for m, _ in rows()])


class FlavorRowTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("audit-admin", "audit@example.com", "pw")
        self.client.force_login(self.admin)
        Logs.objects.all().delete()  # the login's row

    def test_flavor_web_and_api(self):
        from instances.models import Flavor
        from rest_framework.test import APIClient

        data = {"label": "tiny-a", "memory": 512, "vcpu": 1, "disk": 10}
        self.client.post(reverse("instances:flavor_create"), data)
        flavor = Flavor.objects.get(label="tiny-a")
        self.client.post(reverse("instances:flavor_update", args=[flavor.pk]), {**data, "vcpu": 2})
        self.client.post(reverse("instances:flavor_update", args=[flavor.pk]), {**data, "vcpu": 2})  # no change
        self.client.post(reverse("instances:flavor_delete", args=[flavor.pk]))
        self.assertFalse(Flavor.objects.filter(label="tiny-a").exists())

        api = APIClient()
        api.force_authenticate(self.admin)
        data = {"label": "huge-a", "memory": 4096, "vcpu": 4, "disk": 40}
        self.assertEqual(api.post(reverse("instance-flavor-list"), data, format="json").status_code, 201)
        detail = reverse("instance-flavor-detail", args=[Flavor.objects.get(label="huge-a").pk])
        self.assertEqual(api.patch(detail, {"vcpu": 8}, format="json").status_code, 200)
        self.assertEqual(api.put(detail, {**data, "vcpu": 8, "memory": 8192}, format="json").status_code, 200)
        self.assertEqual(Flavor.objects.get(label="huge-a").memory, 8192)
        self.assertEqual(api.delete(detail).status_code, 204)
        self.assertFalse(Flavor.objects.filter(label="huge-a").exists())

        self.assertEqual([m for m, _ in rows()], [
            "Flavor tiny-a: add", "Flavor tiny-a: change vcpu", "Flavor tiny-a: delete",
            "Flavor huge-a: add", "Flavor huge-a: change vcpu", "Flavor huge-a: change memory", "Flavor huge-a: delete",
        ])
