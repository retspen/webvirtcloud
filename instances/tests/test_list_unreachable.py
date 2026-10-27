"""A VM that cannot be read shows as unknown in the lists instead of turning
the whole page into an error page (host down, failed sync, VM gone)."""

from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

from appsettings.models import AppSettings
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import html
from vrtManager.util import OperationError

ERROR = "Connection Failed: No route to host"
UP_INFO = [1, 4194304, 2097152, 3, 0]


class Domain:
    def info(self):
        return UP_INFO


def live(*args, **kwargs):
    return SimpleNamespace(instance=Domain(), get_title=lambda: "", get_uuid=lambda: "uuid")


def unreachable(*args, **kwargs):
    raise OperationError(ERROR)


class UnreachableListTests(TestCase):
    def setUp(self):
        self.client.force_login(
            get_user_model().objects.create_superuser(username="down-admin", password="pwd", email="down@example.com")
        )
        self.compute = Compute.objects.create(name="down-compute", hostname="192.0.2.1", type=1, login="u", password="p")
        self.vm_a = Instance.objects.create(compute=self.compute, name="vm-a", uuid="11111111-1111-1111-1111-111111111111")
        self.vm_b = Instance.objects.create(compute=self.compute, name="vm-b", uuid="22222222-2222-2222-2222-222222222222")

    def get(self, url, wvm_instance, up=False):
        def no_live_host_data(_self):
            raise AssertionError("host data read for a host that is down")

        props = {"status": up, "connection_error": None if up else ERROR}
        patches = [patch.object(Compute, k, new_callable=PropertyMock, return_value=v) for k, v in props.items()]
        for name in ("cpu_count", "ram_size", "ram_usage"):
            if up:
                patches.append(patch.object(Compute, name, new_callable=PropertyMock, return_value=1))
            else:
                patches.append(patch.object(Compute, name, property(no_live_host_data)))
        patches += [
            patch("instances.views.utils.refr"),
            patch("computes.views.utils.refresh_instance_database"),
            patch("instances.models.wvmInstance", side_effect=wvm_instance),
        ]
        for p in patches:
            p.start()
        try:
            response = self.client.get(url)
        finally:
            for p in reversed(patches):
                p.stop()
        self.assertEqual(response.status_code, 200)
        return response

    def assert_unknown(self, response, instances):
        for vm in instances:
            self.assertContains(response, vm.name)
            self.assertNotContains(response, reverse("instances:poweron", args=[vm.id]))
            self.assertNotContains(response, reverse("instances:poweroff", args=[vm.id]))
        states = html.fromstring(response.content).xpath("//span[@data-state]/@data-state")
        self.assertEqual(states.count("Unknown"), len(instances))

    def test_nongrouped_index_lists_the_vms_of_a_down_host(self):
        AppSettings.objects.filter(key="VIEW_INSTANCES_LIST_STYLE").update(value="nongrouped")
        response = self.get(reverse("instances:index"), unreachable)
        self.assert_unknown(response, [self.vm_a, self.vm_b])
        self.assertContains(response, ERROR)

    def test_grouped_index_lists_the_vms_of_a_down_host(self):
        AppSettings.objects.filter(key="VIEW_INSTANCES_LIST_STYLE").update(value="grouped")
        response = self.get(reverse("instances:index"), unreachable)
        self.assert_unknown(response, [self.vm_a, self.vm_b])
        self.assertContains(response, "Not connected")

    def test_one_unreadable_vm_does_not_hide_the_others(self):
        AppSettings.objects.filter(key="VIEW_INSTANCES_LIST_STYLE").update(value="nongrouped")

        def vm_b_gone(*args, uuid=None, **kwargs):
            if uuid == self.vm_b.uuid:
                raise OperationError("Domain not found")
            return live()

        response = self.get(reverse("instances:index"), vm_b_gone, up=True)
        self.assert_unknown(response, [self.vm_b])
        self.assertContains(response, reverse("instances:poweroff", args=[self.vm_a.id]))

    def test_compute_instances_page_of_a_down_host(self):
        response = self.get(reverse("instances", args=[self.compute.id]), unreachable)
        self.assert_unknown(response, [self.vm_a, self.vm_b])
        self.assertContains(response, ERROR)

    def test_compute_instances_page_does_not_claim_a_down_host_is_empty(self):
        Instance.objects.all().delete()
        response = self.get(reverse("instances", args=[self.compute.id]), unreachable)
        self.assertNotContains(response, "have any Instances")
        self.assertContains(response, ERROR)
