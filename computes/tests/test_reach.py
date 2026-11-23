"""Reach asks each host pair and each directory once, however many VMs and
destinations a page asks about."""

from unittest.mock import MagicMock, patch

from computes.models import Compute
from computes.reach import Reach
from django.test import RequestFactory, TestCase
from instances.models import Instance
from libvirt import libvirtError

XML = "<domain><devices><disk type='file'><source file='/shared/{name}.qcow2'/><target dev='vda'/></disk></devices></domain>"


class ReachTests(TestCase):
    def test_hosts_and_directories_are_asked_once(self):
        source = Compute.objects.create(name="re", hostname="192.0.2.60", login="", password="", type=4)
        targets = [Compute.objects.create(name=f"re-{n}", hostname=f"192.0.2.6{n}", login="", password="", type=4)
                   for n in (1, 2)]
        vms = [Instance.objects.create(compute=source, name=f"re-vm{n}", uuid=f"00000000-0000-4000-8000-00000000020{n}")
               for n in range(3)]
        with patch("instances.jobs.migration_target") as target_check, patch("computes.reach.wvmInstances") as conn, \
                patch.object(Instance, "proxy", new_callable=lambda: property(lambda vm: MagicMock(
                    instance=MagicMock(XMLDesc=lambda flags: XML.format(name=vm.name))))):
            conn.return_value.shares.return_value = True
            reach = Reach(RequestFactory().get("/"))
            refusals = [reach.refusal(vm, target) for vm in vms for target in targets]
        self.assertEqual(refusals, [None] * 6)
        self.assertEqual(target_check.call_count, 2)  # a host pair once it passed
        self.assertEqual(conn.return_value.shares.call_count, 2)  # a directory of a host pair once

    def test_a_host_whose_pools_cannot_be_read_is_refused_not_raised(self):
        source = Compute.objects.create(name="rf", hostname="192.0.2.70", login="", password="", type=4)
        target = Compute.objects.create(name="rf-1", hostname="192.0.2.71", login="", password="", type=4)
        vm = Instance.objects.create(compute=source, name="rf-vm", uuid="00000000-0000-4000-8000-000000000301")
        with patch("instances.jobs.migration_target"), patch("computes.reach.wvmInstances") as conn, \
                patch.object(Instance, "proxy", new_callable=lambda: property(lambda vm: MagicMock(
                    instance=MagicMock(XMLDesc=lambda flags: XML.format(name=vm.name))))):
            conn.return_value.shares.side_effect = libvirtError("cannot list pools")
            self.assertIn("cannot list pools", Reach(RequestFactory().get("/")).refusal(vm, target))
