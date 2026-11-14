"""Instance lists read their VMs once a host (get_domain_rows): the states in
one call and each VM's live XML once, no lookup or info call a VM; on
libvirt's test driver."""

from collections import Counter
from unittest.mock import PropertyMock, patch

import libvirt
from appsettings.models import AppSettings
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance

DOMAIN = """<domain type='test'><name>{name}</name><uuid>{uuid}</uuid><title>{name} title</title>
<memory unit='MiB'>4096</memory><currentMemory unit='MiB'>2048</currentMemory><vcpu current='3'>4</vcpu>
<os><type arch='i686'>hvm</type></os></domain>"""
VMS = {"vm-a": "11111111-1111-1111-1111-111111111111", "vm-b": "22222222-2222-2222-2222-222222222222"}


class ListReadTests(TestCase):
    def setUp(self):
        self.client.force_login(
            get_user_model().objects.create_superuser(username="rpc-admin", password="pwd", email="rpc@example.com")
        )
        self.conn = libvirt.open("test:///default")
        self.addCleanup(self.conn.close)
        self.compute = Compute.objects.create(name="rpc-compute", hostname="localhost", type=4, login="", password="")
        for name, uuid in VMS.items():
            domain = self.conn.defineXML(DOMAIN.format(name=name, uuid=uuid))
            domain.create()
            self.addCleanup(domain.undefine)
            self.addCleanup(domain.destroy)
            Instance.objects.create(compute=self.compute, name=name, uuid=uuid)

    def get(self, url):
        calls = Counter()

        def counted(cls, name):
            real = getattr(cls, name)

            def call(*args, **kwargs):
                calls[name] += 1
                return real(*args, **kwargs)

            return patch.object(cls, name, call)

        patches = [patch("instances.views.refresh_instance_database"), patch("computes.views.utils.refresh_instance_database"),
                   patch("vrtManager.connection.connection_manager.get_connection", return_value=self.conn),
                   counted(libvirt.virDomain, "info"), counted(libvirt.virDomain, "XMLDesc"),
                   counted(libvirt.virConnect, "lookupByUUIDString")]
        # the grouped list's host line; the test driver has no memory stats
        patches += [patch.object(Compute, k, new_callable=PropertyMock, return_value=v)
                    for k, v in {"cpu_count": 1, "ram_size": 1024, "ram_usage": 0}.items()]
        for p in patches:
            p.start()
        try:
            response = self.client.get(url)
        finally:
            for p in reversed(patches):
                p.stop()
        self.assertEqual(response.status_code, 200)
        return response, calls

    def assert_read_once_a_host(self, url):
        response, calls = self.get(url)
        # each VM the list shows once; the host's other domains (the test driver's own) not at all
        self.assertEqual(calls, {"XMLDesc": len(VMS)})
        self.assertContains(response, "2048 MiB", count=len(VMS))
        self.assertContains(response, "Active")
        self.assertContains(response, "vm-a title")

    def test_nongrouped_index(self):
        AppSettings.objects.filter(key="VIEW_INSTANCES_LIST_STYLE").update(value="nongrouped")
        self.assert_read_once_a_host(reverse("instances:index"))

    def test_grouped_index(self):
        AppSettings.objects.filter(key="VIEW_INSTANCES_LIST_STYLE").update(value="grouped")
        self.assert_read_once_a_host(reverse("instances:index"))

    def test_compute_instances(self):
        self.assert_read_once_a_host(reverse("instances", args=[self.compute.id]))

    def test_a_user_s_list_reads_only_their_vms(self):
        from accounts.models import UserInstance

        user = get_user_model().objects.create_user("rpc-user", password="pwd")
        UserInstance.objects.create(user=user, instance=Instance.objects.get(name="vm-a"))
        self.client.force_login(user)
        response, calls = self.get(reverse("instances:index"))
        # the other VMs of the host, the test driver's own and other tests' included, are not read
        self.assertEqual(calls, {"XMLDesc": 1})
        self.assertContains(response, "vm-a title")
        self.assertNotContains(response, "vm-b")
