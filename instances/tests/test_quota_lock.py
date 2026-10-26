import threading
import time
from unittest.mock import patch

from accounts.models import UserInstance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from instances.models import Instance

QUOTA_CPUS = 4


# Sessions and messages in cookies: concurrent writes to the in-memory test
# database would fail for reasons unrelated to the quota race.
@override_settings(
    SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
    MESSAGE_STORAGE="django.contrib.messages.storage.cookie.CookieStorage",
)
class QuotaRaceTestCase(TransactionTestCase):
    """Two concurrent resizes of one user's VMs must not both pass the quota."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("quota_user", password="pw")
        compute = Compute.objects.create(name="quota-compute", hostname="127.0.0.1", login="", password="", type=4)
        self.vms = [
            Instance.objects.create(compute=compute, name=f"quota-vm-{i}", uuid=f"1111111{i}-2222-3333-4444-555555555555")
            for i in range(2)
        ]
        for vm in self.vms:
            UserInstance.objects.create(user=self.user, instance=vm, is_change=True)
        self.allocated = 2  # two VMs with one vCPU each

    def fake_quota(self, user, instance, cpu, memory, disk):
        seen = self.allocated
        time.sleep(0.3)  # widen the window between the check and the change
        return "cpu" if seen + cpu > QUOTA_CPUS else ""

    def fake_resize(self, cur_vcpu, vcpu):
        self.allocated += int(vcpu) - 1

    def resize(self, vm):
        client = Client()
        client.force_login(self.user)
        client.post(reverse("instances:resizevm_cpu", args=[vm.id]), {"vcpu": 3, "cur_vcpu": 3})
        connection.close()

    def test_second_concurrent_resize_is_refused(self):
        with patch("instances.views.utils.check_user_quota", self.fake_quota), patch(
            "instances.models.wvmInstance"
        ) as wvm:
            wvm.return_value.get_vcpu.return_value = 1
            wvm.return_value.instance.isActive.return_value = False  # vCPUs change on a shut-off VM
            wvm.return_value.resize_cpu.side_effect = self.fake_resize
            threads = [threading.Thread(target=self.resize, args=(vm,)) for vm in self.vms]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(wvm.return_value.resize_cpu.call_count, 1)
        self.assertLessEqual(self.allocated, QUOTA_CPUS)
