"""check_user_quota counts every VM of the user and refuses an increase it
cannot verify (fail closed); requests that add nothing are not checked."""

from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

from accounts.models import UserAttributes, UserInstance
from appsettings.settings import get_settings
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from instances.utils import QUOTA_UNVERIFIED, check_user_quota
from libvirt import VIR_DOMAIN_PAUSED, VIR_DOMAIN_RUNNING
from vrtManager.util import OperationError


def vm_reader(vcpu=2, memory=1024, disk_gib=10):
    def make(*args, **kwargs):
        return SimpleNamespace(
            get_vcpu=lambda: vcpu,
            get_memory=lambda: memory,
            get_disk_devices=lambda: [{"size": disk_gib << 30}],
        )

    return make


class QuotaTests(TestCase):
    def setUp(self):
        get_settings()  # app settings are normally loaded by middleware
        self.user = get_user_model().objects.create_user("quota-user", password="pw")
        UserAttributes.objects.create(user=self.user, max_instances=5, max_cpus=8, max_memory=8192, max_disk_size=100)
        self.up = Compute.objects.create(name="up", hostname="wvc-alias", login="root", password="", type=2)
        self.down = Compute.objects.create(name="down", hostname="192.0.2.1", login="u", password="p", type=1)
        self.status_checks = []

    def own(self, compute, n):
        vm = Instance.objects.create(compute=compute, name=f"vm-{compute.name}-{n}", uuid=f"{n:08d}-0000-0000-0000-{compute.pk:012d}")
        UserInstance.objects.create(user=self.user, instance=vm)
        return vm

    def check(self, *delta, reader=None):
        test = self

        def status(compute):
            test.status_checks.append(id(compute))
            return compute.pk != test.down.pk

        reader = reader or vm_reader()
        with patch.object(Compute, "status", property(status)), patch(
            "instances.utils.wvmInstance", side_effect=reader
        ) as wvm:
            result = check_user_quota(self.user, *delta)
        return result.split(" ")[0], wvm.call_count  # without the QUOTA_DEBUG detail

    def test_vms_on_a_host_without_a_tcp_route_are_counted(self):
        # an ssh_config alias: the old TCP probe failed and skipped these VMs
        for n in range(4):
            self.own(self.up, n)
        self.assertEqual(self.check(0, 1, 0, 0), ("cpu", 4))

    def test_a_host_that_is_down_refuses_an_increase(self):
        self.own(self.up, 1)
        self.own(self.down, 2)
        self.assertEqual(self.check(0, 1, 0, 0)[0], QUOTA_UNVERIFIED)

    def test_a_vm_that_cannot_be_read_refuses_an_increase(self):
        self.own(self.up, 1)

        def gone(*args, **kwargs):
            raise OperationError("Domain not found")

        self.assertEqual(self.check(0, 0, 512, 0, reader=gone)[0], QUOTA_UNVERIFIED)

    def test_each_host_is_checked_once(self):
        for n in range(3):
            self.own(self.up, n)
        self.check(0, 1, 0, 0)
        # one Compute object asked (its status is cached), not one per VM
        self.assertEqual(len(set(self.status_checks)), 1)

    def test_a_user_over_quota_can_still_shrink(self):
        for n in range(5):
            self.own(self.up, n)  # 10 vCPUs used of 8
        self.assertEqual(self.check(0, -1, 0, 0), ("", 0))
        self.assertEqual(self.check(0, 0, -512, 0), ("", 0))

    def test_unlimited_users_are_not_checked(self):
        UserAttributes.objects.filter(user=self.user).update(max_instances=-1, max_cpus=-1, max_memory=-1, max_disk_size=-1)
        self.own(self.down, 1)
        self.assertEqual(self.check(1, 4, 4096, 50), ("", 0))

    def test_only_an_instance_limit_needs_no_host(self):
        UserAttributes.objects.filter(user=self.user).update(max_instances=2, max_cpus=-1, max_memory=-1, max_disk_size=-1)
        self.own(self.down, 1)
        self.assertEqual(self.check(1, 4, 4096, 50), ("", 0))
        self.own(self.up, 2)
        self.assertEqual(self.check(1, 4, 4096, 50), ("instance", 0))

    def test_instance_limit_is_checked_before_any_host(self):
        for n in range(5):
            self.own(self.down, n)
        self.assertEqual(self.check(1, 0, 0, 0), ("instance", 0))

    def test_templates_are_not_counted(self):
        for n in range(4):
            vm = self.own(self.up, n)
        Instance.objects.filter(pk=vm.pk).update(is_template=True)
        self.assertEqual(self.check(0, 2, 0, 0), ("", 3))

    def test_zero_allows_none_and_minus_one_has_no_limit(self):
        # 0 takes a quota away from the user; -1 lifts it
        ua = UserAttributes.objects.get(user=self.user)
        for field, delta, refused in (("max_instances", (1, 0, 0, 0), "instance"), ("max_cpus", (0, 1, 0, 0), "cpu"),
                                      ("max_memory", (0, 0, 512, 0), "memory"), ("max_disk_size", (0, 0, 0, 1), "disk")):
            with self.subTest(field=field):
                setattr(ua, field, 0)
                ua.save()
                self.assertEqual(self.check(*delta)[0], refused)
                setattr(ua, field, -1)
                ua.save()
                self.assertEqual(self.check(*delta)[0], "")

    def test_the_numbers_show_only_with_quota_debug_on(self):
        # the setting is the text "True" or "False": "False" turns them off
        from appsettings.models import AppSettings

        for i in range(5):
            self.own(self.up, i)
        for value, expected in (("True", "instance (6 > 5)"), ("False", "instance")):
            with self.subTest(value=value):
                AppSettings.objects.filter(key="QUOTA_DEBUG").update(value=value)
                get_settings()
                with patch.object(Compute, "status", True), patch("instances.utils.wvmInstance", side_effect=vm_reader()):
                    self.assertEqual(check_user_quota(self.user, 1, 0, 0, 0), expected)


class QuotaViewTests(TestCase):
    """The resize views turn the result into a message and charge only what changes."""

    def setUp(self):
        get_settings()
        self.user = get_user_model().objects.create_user("quota-view-user", password="pw")
        self.client.force_login(self.user)
        compute = Compute.objects.create(name="qv", hostname="10.0.0.1", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=compute, name="qv-vm", uuid="12121212-0000-0000-0000-000000000000")
        UserInstance.objects.create(user=self.user, instance=self.vm, is_change=True)

    def post(self, view, data, quota="", status=VIR_DOMAIN_RUNNING):
        with patch("instances.views.utils.check_user_quota", return_value=quota) as check, patch(
            "instances.models.wvmInstance"
        ) as wvm:
            wvm.return_value.get_vcpu.return_value = 1
            wvm.return_value.get_memory.return_value = 2048
            wvm.return_value.get_cur_memory.return_value = 2048
            wvm.return_value.get_status.return_value = status
            wvm.return_value.instance.isActive.return_value = status != 5
            response = self.client.post(reverse(view, args=[self.vm.id]), data)
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        return messages, check, wvm.return_value

    def test_unverified_quota_has_its_own_message(self):
        messages, _, proxy = self.post("instances:resizevm_cpu", {"vcpu": 2, "cur_vcpu": 2}, quota=QUOTA_UNVERIFIED,
                                         status=5)
        self.assertEqual(len(messages), 1)
        self.assertIn("a host of your virtual machines cannot be reached", messages[0])
        self.assertNotIn("quota reached", messages[0])
        proxy.resize_cpu.assert_not_called()

    def test_running_vm_memory_charges_no_maximum_change(self):
        # a running VM keeps its maximum: resize_mem changes the current memory only
        _, check, proxy = self.post("instances:resize_memory", {"memory": 8192, "cur_memory": 1024})
        self.assertEqual(check.call_args.args[1:], (0, 0, 0, 0))
        # the maximum passed is the current one: if the VM shut down meanwhile,
        # resize_mem would write it, and it must not be the unchecked 8192
        proxy.resize_mem.assert_called_once_with("1024", 2048)

    def test_paused_vm_memory_charges_no_maximum_change(self):
        _, check, proxy = self.post("instances:resize_memory", {"memory": 8192, "cur_memory": 1024}, status=VIR_DOMAIN_PAUSED)
        self.assertEqual(check.call_args.args[1:], (0, 0, 0, 0))
        proxy.resize_mem.assert_called_once_with("1024", 2048)

    def test_shut_off_vm_memory_charges_the_maximum_change(self):
        _, check, _ = self.post("instances:resize_memory", {"memory": 4096, "cur_memory": 1024}, status=5)
        self.assertEqual(check.call_args.args[1:], (0, 0, 2048, 0))


class DetailPageQuotaTests(TestCase):
    def test_the_detail_page_does_not_read_every_vm_for_the_quota(self):
        get_settings()
        user = get_user_model().objects.create_user("quota-detail-user", password="pw")
        compute = Compute.objects.create(name="qd", hostname="10.0.0.1", login="u", password="p", type=1)
        vm = Instance.objects.create(compute=compute, name="qd-vm", uuid="34343434-0000-0000-0000-000000000000")
        UserInstance.objects.create(user=user, instance=vm)
        self.client.force_login(user)
        with patch("instances.models.wvmInstance") as wvm, patch(
            "instances.views.utils.check_user_quota", side_effect=AssertionError("quota checked on GET")
        ), patch.object(Compute, "status", new_callable=PropertyMock, return_value=True):
            proxy = wvm.return_value
            proxy.get_memory.return_value = 1024
            proxy.get_cur_memory.return_value = 1024
            proxy.get_max_memory.return_value = 4096
            for name in ("get_networks", "get_ifaces", "get_storages", "get_disk_devices", "get_media_devices", "get_net_devices"):
                getattr(proxy, name).return_value = []
            proxy.get_hostdevs.return_value = ([], [], [])
            proxy.get_status.return_value = 5
            response = self.client.get(reverse("instances:instance", args=[vm.id]))
        self.assertEqual(response.status_code, 200)
