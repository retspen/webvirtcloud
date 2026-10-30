"""The Resize tab changes only what was asked, and refuses what libvirt would
not apply as asked."""

from unittest.mock import patch

from accounts.models import UserInstance
from appsettings.settings import get_settings
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from libvirt import VIR_DOMAIN_RUNNING

GIB = 1 << 30


class ResizeInputTests(TestCase):
    def setUp(self):
        get_settings()
        self.user = get_user_model().objects.create_user("resize-user", password="pw")
        self.client.force_login(self.user)
        compute = Compute.objects.create(name="rs", hostname="192.0.2.1", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=compute, name="rs-vm", uuid="13131313-0000-0000-0000-000000000000")
        UserInstance.objects.create(user=self.user, instance=self.vm, is_change=True)

    def post(self, view, data, status=5, disks=()):
        with patch("instances.views.utils.check_user_quota", return_value=""), patch(
            "instances.models.wvmInstance"
        ) as wvm:
            proxy = wvm.return_value
            proxy.get_vcpu.return_value = 2
            proxy.get_memory.return_value = 2048
            proxy.get_cur_memory.return_value = 2048
            proxy.get_status.return_value = status
            proxy.instance.isActive.return_value = status != 5
            proxy.get_disk_devices.return_value = [dict(disk) for disk in disks]
            response = self.client.post(reverse(view, args=[self.vm.id]), data)
        self.assertEqual(response.status_code, 302)
        return [str(m) for m in get_messages(response.wsgi_request)], proxy

    def test_only_a_disk_given_a_larger_size_grows(self):
        # a 3.5 GiB disk left as it was is not grown; a disk outside a pool has no size
        disks = [{"dev": "vda", "size": 3 * GIB + GIB // 2}, {"dev": "vdb", "size": 20 * GIB}, {"dev": "vdc", "size": None}]
        messages, proxy = self.post("instances:resize_disk", {"disk_size_vda": "", "disk_size_vdb": "30"}, disks=disks)
        proxy.resize_disk.assert_called_once()
        self.assertEqual([(d["dev"], d["size_new"]) for d in proxy.resize_disk.call_args.args[0]], [("vdb", 30 * GIB)])
        self.assertEqual(messages, ["Disk is resized: vdb"])

    def test_a_smaller_disk_size_refuses_every_change(self):
        # a disk does not shrink: one smaller size leaves the others as they are too
        disks = [{"dev": "vda", "size": 10 * GIB}, {"dev": "vdb", "size": 20 * GIB}]
        messages, proxy = self.post("instances:resize_disk", {"disk_size_vda": "5", "disk_size_vdb": "30"}, disks=disks)
        proxy.resize_disk.assert_not_called()
        self.assertEqual(messages, ["vda is 10.0\xa0GB: a disk cannot shrink"])

    def test_vcpus_and_memory_must_be_at_least_one(self):
        for view, data, setter in (("instances:resizevm_cpu", {"vcpu": "2", "cur_vcpu": "0"}, "resize_cpu"),
                                   ("instances:resize_memory", {"memory": "2048", "cur_memory": "-1"}, "resize_mem")):
            with self.subTest(view):
                messages, proxy = self.post(view, data)
                getattr(proxy, setter).assert_not_called()
                self.assertTrue(messages[-1].startswith("Enter a whole number"), messages)

    def test_a_cpu_resize_says_what_the_vm_gets(self):
        messages, proxy = self.post("instances:resizevm_cpu", {"vcpu": "4", "cur_vcpu": "2"})
        proxy.resize_cpu.assert_called_once_with("2", "4")
        self.assertEqual(messages, ["vCPUs set to 2 (maximum 4)"])

    def test_a_disk_size_that_is_not_a_whole_number_is_refused(self):
        messages, proxy = self.post("instances:resize_disk", {"disk_size_vda": "4.5"}, disks=[{"dev": "vda", "size": GIB}])
        proxy.resize_disk.assert_not_called()
        self.assertEqual(messages, ["Enter disk sizes as whole GiB"])

    def test_vcpus_change_only_on_a_shut_off_vm(self):
        messages, proxy = self.post("instances:resizevm_cpu", {"vcpu": "4", "cur_vcpu": "4"}, status=VIR_DOMAIN_RUNNING)
        proxy.resize_cpu.assert_not_called()
        self.assertEqual(messages, ["Shut off the VM to change its vCPUs"])

    def test_current_vcpus_above_the_maximum_are_refused(self):
        messages, proxy = self.post("instances:resizevm_cpu", {"vcpu": "2", "cur_vcpu": "4"})
        proxy.resize_cpu.assert_not_called()
        self.assertEqual(messages, ["The current vCPUs cannot be more than the maximum"])

    def test_current_memory_above_the_maximum_is_refused(self):
        messages, proxy = self.post("instances:resize_memory", {"memory": "4096", "cur_memory": "8192"})
        proxy.resize_mem.assert_not_called()
        self.assertEqual(messages, ["The current memory cannot be more than the maximum"])

    def test_a_running_vm_offers_no_maximum_memory(self):
        with patch("instances.models.wvmInstance"):
            self.vm.__dict__["status"] = VIR_DOMAIN_RUNNING
            from django.template.loader import render_to_string
            html = render_to_string("instances/resize_tab.html", {"instance": self.vm, "can_change": True})
        self.assertRegex(html, r'<input [^>]*name="memory"[^>]*disabled>')
