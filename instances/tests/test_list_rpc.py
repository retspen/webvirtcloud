"""Instance lists ask libvirt for a VM's info once per row."""

from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

from appsettings.models import AppSettings
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance

# virDomainGetInfo: state, max memory KiB, memory KiB, vCPUs, CPU time
INFO = [1, 4194304, 2097152, 3, 0]


class FakeDomain:
    # a plain class: Django templates do not call MagicMock attributes
    def __init__(self):
        self.info_calls = 0
        self.xml_calls = 0

    def info(self):
        self.info_calls += 1
        return INFO

    def XMLDesc(self, flags=0):
        self.xml_calls += 1
        return "<domain><title></title><currentMemory>2097152</currentMemory></domain>"


class ListInfoCallTests(TestCase):
    def setUp(self):
        self.client.force_login(
            get_user_model().objects.create_superuser(username="rpc-admin", password="pwd", email="rpc@example.com")
        )
        self.compute = Compute.objects.create(name="rpc-compute", hostname="localhost", type=4, login="", password="")
        Instance.objects.create(compute=self.compute, name="vm-a", uuid="11111111-1111-1111-1111-111111111111")
        Instance.objects.create(compute=self.compute, name="vm-b", uuid="22222222-2222-2222-2222-222222222222")
        self.domains = []

    def proxy(self, *args, **kwargs):
        domain = FakeDomain()
        self.domains.append(domain)
        return SimpleNamespace(
            instance=domain,
            get_uuid=lambda: "uuid",
            get_title=lambda: domain.XMLDesc() and "",
            get_cur_memory=lambda: int(domain.XMLDesc().split(">")[4].split("<")[0]) // 1024,
        )

    def get(self, url):
        compute_patches = {"status": True, "cpu_count": 1, "ram_size": 1024, "ram_usage": 0}
        with patch("instances.views.utils.refr"), patch("computes.views.utils.refresh_instance_database"), patch(
            "instances.models.wvmInstance", side_effect=self.proxy
        ):
            patches = [patch.object(Compute, k, new_callable=PropertyMock, return_value=v) for k, v in compute_patches.items()]
            for p in patches:
                p.start()
            try:
                response = self.client.get(url)
            finally:
                for p in patches:
                    p.stop()
        self.assertEqual(response.status_code, 200)
        return response

    def assert_one_info_per_vm(self, response):
        self.assertEqual(len(self.domains), 2, "one proxy per VM row")
        for domain in self.domains:
            self.assertEqual(domain.info_calls, 1)
            self.assertEqual(domain.xml_calls, 1, "only the title reads the XML")
        self.assertContains(response, "2048 MiB", count=2)
        self.assertContains(response, "Active")

    def test_nongrouped_index(self):
        AppSettings.objects.filter(key="VIEW_INSTANCES_LIST_STYLE").update(value="nongrouped")
        self.assert_one_info_per_vm(self.get(reverse("instances:index")))

    def test_grouped_index(self):
        AppSettings.objects.filter(key="VIEW_INSTANCES_LIST_STYLE").update(value="grouped")
        self.assert_one_info_per_vm(self.get(reverse("instances:index")))

    def test_compute_instances(self):
        # this page shows the maximum memory, as before
        # the VM's current memory, as on the Instances page, not its maximum
        self.assert_one_info_per_vm(self.get(reverse("instances", args=[self.compute.id])))
