"""One libvirt host is one compute, and a compute's VMs stay on their host:
the host UUID of a new or changed connection is read and checked."""

from unittest.mock import MagicMock, PropertyMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from libvirt import libvirtError
from operations import claims
from operations.models import Claim

from computes.models import Compute

# the host each address reaches, by its UUID; an address not here does not answer
HOSTS = {"192.0.2.1": "11111111-1111-1111-1111-111111111111", "kvm1.example.org": "11111111-1111-1111-1111-111111111111",
         "192.0.2.2": "22222222-2222-2222-2222-222222222222"}


def host(hostname, login, password, conn_type):
    if hostname not in HOSTS:
        raise libvirtError(f"{hostname} did not answer within 5 s")
    return MagicMock(**{"host_uuid.return_value": HOSTS[hostname]})


class HostIdentityTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("hi-admin", "hi@example.com", "pw"))
        patcher = patch("computes.models.wvmHostDetails", side_effect=host)
        patcher.start()
        self.addCleanup(patcher.stop)

    def add(self, name, hostname):
        return self.client.post(reverse("add_tcp_host"), {"name": name, "hostname": hostname, "login": "wvc",
                                                          "password": "pw", "details": "", "type": 1})

    def edit(self, compute, hostname):
        return self.client.post(reverse("compute_update", args=[compute.id]),
                                {"name": compute.name, "hostname": hostname, "login": "wvc", "password": "",
                                 "details": "", "type": 1})

    def test_a_host_is_added_once_whatever_it_is_reached_by(self):
        self.add("kvm1", "192.0.2.1")
        self.assertEqual(Compute.objects.get(name="kvm1").host_uuid, HOSTS["192.0.2.1"])
        response = self.add("kvm1-again", "kvm1.example.org")
        self.assertContains(response, "This host is already added as kvm1")
        self.assertFalse(Compute.objects.filter(name="kvm1-again").exists())

    def test_a_compute_added_before_is_recorded_on_the_computes_page(self):
        Compute.objects.create(name="old", hostname="192.0.2.1", login="wvc", password="pw", type=1)
        with patch.object(Compute, "status", new_callable=PropertyMock, return_value=True), \
                patch("computes.views.shown_capacity", return_value=None):
            self.client.get(reverse("computes"))
        self.assertEqual(Compute.objects.get(name="old").host_uuid, HOSTS["192.0.2.1"])
        self.assertContains(self.add("new", "kvm1.example.org"), "This host is already added as old")

    def test_a_compute_with_vms_whose_host_is_not_known_keeps_its_connection(self):
        compute = Compute.objects.create(name="old", hostname="192.0.2.9", login="wvc", password="pw", type=1)
        Instance.objects.create(compute=compute, name="web-1", uuid="33333333-3333-3333-3333-333333333333")
        self.assertContains(self.edit(compute, "192.0.2.2"), "The host its VMs are on is not known yet")
        compute.refresh_from_db()
        self.assertEqual(compute.hostname, "192.0.2.9")

    def test_a_compute_with_vms_moves_only_to_an_address_of_their_host(self):
        self.add("kvm1", "192.0.2.1")
        compute = Compute.objects.get(name="kvm1")
        Instance.objects.create(compute=compute, name="web-1", uuid="33333333-3333-3333-3333-333333333333")
        self.assertContains(self.edit(compute, "192.0.2.2"), "This is another host than the one its VMs")
        self.assertContains(self.edit(compute, "192.0.2.9"), "The panel cannot reach the host to tell that its VMs")
        self.edit(compute, "kvm1.example.org")
        compute.refresh_from_db()
        self.assertEqual((compute.hostname, compute.host_uuid), ("kvm1.example.org", HOSTS["192.0.2.1"]))

    def test_a_compute_without_vms_may_be_another_host_or_none_yet(self):
        self.add("kvm", "192.0.2.9")  # added while it does not answer
        compute = Compute.objects.get(name="kvm")
        self.assertEqual(compute.host_uuid, "")
        self.edit(compute, "192.0.2.2")
        compute.refresh_from_db()
        self.assertEqual(compute.host_uuid, HOSTS["192.0.2.2"])

    def test_a_change_is_checked_while_the_compute_is_held(self):
        # no VM list can add the old host's VMs between the check and the save
        compute = Compute.objects.create(name="kvm", hostname="192.0.2.9", login="wvc", password="pw", type=1)
        held = []

        def checked(*args):
            held.append(set(Claim.objects.values_list("resource", "mode")))
            return host(*args)

        with patch("computes.models.wvmHostDetails", side_effect=checked):
            self.edit(compute, "192.0.2.2")
            self.client.patch(f"/api/v1/computes/{compute.id}/", {"hostname": "192.0.2.1"}, content_type="application/json")
        for claimed in held:
            self.assertLessEqual({(claims.compute_key(compute.id), Claim.EXCLUSIVE), (claims.hosts_key(), Claim.EXCLUSIVE)},
                                 claimed)
        self.assertEqual(len(held), 2)

    def test_the_api_checks_the_host_too(self):
        self.add("kvm1", "192.0.2.1")
        data = {"name": "kvm1-api", "hostname": "kvm1.example.org", "login": "wvc", "password": "pw", "type": 1}
        response = self.client.post("/api/v1/computes/", data, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("This host is already added as kvm1", str(response.json()))
        data["hostname"] = "192.0.2.2"
        self.assertEqual(self.client.post("/api/v1/computes/", data, content_type="application/json").status_code, 201)
        self.assertEqual(Compute.objects.get(name="kvm1-api").host_uuid, HOSTS["192.0.2.2"])
