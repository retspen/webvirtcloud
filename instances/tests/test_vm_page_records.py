"""The VM page reads the user's rights from the VM's own record, and a VM
removed outside the panel sends the user back to the list."""

from unittest.mock import PropertyMock, patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from libvirt import VIR_ERR_NO_DOMAIN, libvirtError

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance


class VmPageRecordsTestCase(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("rows-owner", password="x")
        self.compute = Compute.objects.create(name="rows-c", hostname="192.0.2.70", login="root", password="", type=1)
        self.vm = Instance.objects.create(compute=self.compute, name="web", uuid="aaaaaaaa-0000-0000-0000-000000000071")
        UserInstance.objects.create(instance=self.vm, user=self.owner, is_change=False)
        self.client.force_login(self.owner)

    def page(self, wvm_error=None):
        with patch("instances.models.wvmInstance", side_effect=wvm_error) as wvm, patch.object(
            Compute, "status", new_callable=PropertyMock, return_value=True
        ):
            proxy = wvm.return_value
            proxy.get_memory.return_value = proxy.get_cur_memory.return_value = 1024
            proxy.get_max_memory.return_value = 4096
            proxy.get_hostdevs.return_value = ([], [], [])
            proxy.get_console_type.return_value = "vnc"
            proxy.get_status.return_value = 5
            for getter in ("get_networks", "get_ifaces", "get_storages", "get_disk_devices", "get_media_devices",
                           "get_net_devices"):
                getattr(proxy, getter).return_value = []
            return self.client.get(reverse("instances:instance", args=[self.vm.id]))

    def test_the_rights_come_from_the_vms_own_record(self):
        # another VM of the same name on the compute, owned with more rights:
        # its record was not refreshed after a rename outside the panel
        other = Instance.objects.create(compute=self.compute, name="web", uuid="aaaaaaaa-0000-0000-0000-000000000072")
        UserInstance.objects.create(instance=other, user=self.owner, is_change=True)
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["userinstance"].instance, self.vm)

    def test_a_vm_removed_outside_the_panel_sends_the_user_to_the_list(self):
        error = libvirtError("Domain not found")
        error.get_error_code = lambda: VIR_ERR_NO_DOMAIN
        response = self.page(wvm_error=error)
        self.assertRedirects(response, reverse("instances:index"), fetch_redirect_response=False)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], ["'web' is no longer on its host."])
