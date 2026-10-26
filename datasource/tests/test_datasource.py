import json

import yaml
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import UserInstance, UserSSHKey
from computes.models import Compute
from instances.models import Instance
from datasource.views import get_client_ip, get_hostname_by_ip


class DataSourceTestCase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.client.login(request=RequestFactory().get("/"), username="admin", password="admin")
        self.compute = Compute.objects.create(
            name="test_compute",
            hostname="localhost",
            type=1,
        )

    def test_os_index(self):
        response = self.client.get(reverse("ds_openstack_index"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("latest", response.content.decode("utf-8"))

    def test_os_metadata_json_latest(self):
        response = self.client.get(reverse("ds_openstack_metadata", args=["latest"]))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content.decode("utf-8"))
        self.assertEqual(data["uuid"], "iid-dswebvirtcloud")
        self.assertIn("hostname", data)

    def test_os_metadata_json_invalid_version(self):
        response = self.client.get(reverse("ds_openstack_metadata", args=["v1"]))
        self.assertEqual(response.status_code, 404)

    def test_os_userdata_invalid_version(self):
        response = self.client.get(reverse("ds_openstack_userdata", args=["v1"]))
        self.assertEqual(response.status_code, 404)

    def test_get_client_ip_direct(self):
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "192.168.1.10"
        self.assertEqual(get_client_ip(request), "192.168.1.10")

    def test_get_client_ip_forwarded(self):
        request = self.factory.get("/")
        request.META["HTTP_X_FORWARDED_FOR"] = "10.0.0.1, 192.168.1.50"
        self.assertEqual(get_client_ip(request), "192.168.1.50")

    def test_get_hostname_by_ip_without_an_entry(self):
        self.assertIsNone(get_hostname_by_ip("256.256.256.256"))

    def test_vdi_url_not_found_compute(self):
        response = self.client.get(reverse("vdi_url", args=[9999, "vm1"]))
        self.assertEqual(response.status_code, 404)


class CloudInitTestCase(TestCase):
    """VMs fetch the cloud-init endpoints without logging in; keys go only to
    a VM whose name is unique."""

    KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOwner owner@example"

    def setUp(self):
        self.compute = Compute.objects.create(name="ci-a", hostname="a.example", login="", password="", type=4)
        self.owner = get_user_model().objects.create_user("ci_owner", password="pw")
        UserSSHKey.objects.create(user=self.owner, keyname="k", keypublic=self.KEY)
        self.vm = Instance.objects.create(compute=self.compute, name="web1", uuid="11111111-2222-3333-4444-999999999991")
        UserInstance.objects.create(instance=self.vm, user=self.owner)
        patcher = patch("datasource.views.get_hostname_by_ip", return_value="web1.lan")
        self.reverse_dns = patcher.start()
        self.addCleanup(patcher.stop)

    def userdata(self):
        response = self.client.get(reverse("ds_openstack_userdata", args=["latest"]))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_endpoints_need_no_login(self):
        for name, args in (("ds_openstack_index", []), ("ds_openstack_metadata", ["latest"])):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)
        self.assertEqual(json.loads(self.client.get(reverse("ds_openstack_metadata", args=["latest"])).content)["hostname"], "web1.lan")

    def test_owner_keys_for_a_unique_name(self):
        self.assertIn(self.KEY, self.userdata())

    def test_no_keys_when_the_name_is_taken_twice(self):
        other = Compute.objects.create(name="ci-b", hostname="b.example", login="", password="", type=4)
        Instance.objects.create(compute=other, name="web1", uuid="11111111-2222-3333-4444-999999999992")
        self.assertNotIn("ssh", self.userdata())

    def test_no_keys_for_an_unknown_name(self):
        self.vm.delete()
        self.assertNotIn("ssh", self.userdata())

    def test_no_keys_for_an_address_without_a_reverse_dns_entry(self):
        # the address's first number is no VM's name: a VM named "10" gets nothing
        self.reverse_dns.return_value = None
        Instance.objects.create(compute=self.compute, name="127", uuid="11111111-2222-3333-4444-999999999993")
        self.assertNotIn("ssh", self.userdata())
        metadata = json.loads(self.client.get(reverse("ds_openstack_metadata", args=["latest"])).content)
        self.assertEqual(metadata["hostname"], "127.0.0.1")

    def test_a_key_comment_stays_one_string(self):
        key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOwner it's: mine"
        UserSSHKey.objects.filter(user=self.owner).update(keypublic=key)
        self.assertEqual(yaml.safe_load(self.userdata())["ssh_authorized_keys"], [key])
