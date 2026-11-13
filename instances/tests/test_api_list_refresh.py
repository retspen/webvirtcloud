"""The REST API's list of all VMs reads the hosts first, as the VM list
does: a VM removed, renamed or defined outside the panel is seen there too,
not only after someone opens a web list."""

from unittest.mock import patch

from accounts.models import UserInstance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from instances.models import Instance


class ApiListRefreshTests(TestCase):
    def setUp(self):
        self.mine, self.other = (Compute.objects.create(name=name, hostname=f"192.0.2.{n}", login="", password="", type=1)
                                 for n, name in ((1, "mine"), (2, "other")))
        self.owner = get_user_model().objects.create_user("api-owner")
        vm = Instance.objects.create(compute=self.mine, name="vm", uuid="11111111-1111-1111-1111-111111111111")
        UserInstance.objects.create(user=self.owner, instance=vm)

    def listed_hosts(self, user):
        self.client.force_login(user)
        with patch("instances.api.viewsets.host_domain_states") as states, \
                patch("instances.api.viewsets.utils.refresh_instance_database") as refresh:
            self.assertEqual(self.client.get("/api/v1/instances/").status_code, 200)
        self.assertEqual([c.name for c in states.call_args.args[0]], [c.name for c in refresh_args(refresh)])
        return sorted(c.name for c in refresh_args(refresh))

    def test_the_hosts_are_read_first(self):
        admin = get_user_model().objects.create_superuser("api-admin", "a@example.com", "pw")
        self.assertEqual(self.listed_hosts(admin), ["mine", "other"])

    def test_an_owner_reads_only_their_vms_hosts(self):
        self.assertEqual(self.listed_hosts(self.owner), ["mine"])


def refresh_args(refresh):
    return [call.args[0] for call in refresh.call_args_list]
