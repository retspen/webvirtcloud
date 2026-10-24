"""The Instances page's search for the VMs using an address
(instances.views.find_address): scope by permission, and what each user sees."""

from unittest.mock import patch

from accounts.models import UserInstance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances import addresses
from instances.models import Instance
from lxml import html

UUID_A = "11111111-2222-3333-4444-00000000000a"
UUID_B = "11111111-2222-3333-4444-00000000000b"
UNKNOWN = "11111111-2222-3333-4444-00000000000c"


def row(uuid, name, compute_id, address="192.0.2.10"):
    return {"uuid": uuid, "name": name, "compute_id": compute_id, "mac": "52:54:00:00:00:01",
            "address": address, "sources": ["agent"], "conflict": False}


class FindAddressTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("fa-admin", "fa@example.com", "pw")
        self.owner = User.objects.create_user("fa-owner", password="pw")
        self.c1 = Compute.objects.create(name="host-one", hostname="192.0.2.1", login="u", password="p", type=1)
        self.c2 = Compute.objects.create(name="host-two", hostname="192.0.2.2", login="u", password="p", type=1)
        self.a = Instance.objects.create(compute=self.c1, name="vm-a", uuid=UUID_A)
        self.b = Instance.objects.create(compute=self.c2, name="vm-b", uuid=UUID_B)
        UserInstance.objects.create(user=self.owner, instance=self.a)

    def search(self, user, q="192.0.2.10", result=None, side_effect=None):
        self.client.force_login(user)
        answer = {"matches": [], "checked": 1, "no_agent": 0, "unread": 0, "hosts_down": [],
                  "hosts_unfinished": [], **(result or {})}
        with patch("instances.addresses.find", return_value=answer, side_effect=side_effect) as find:
            response = self.client.get(reverse("instances:find_address"), {"q": q})
        return response, find

    def test_an_administrator_gets_hosts_and_unregistered_vms(self):
        response, find = self.search(self.admin, result={
            "matches": [row(UUID_A, "vm-a", self.c1.id), row(UNKNOWN, "made-with-virsh", self.c2.id)],
            "hosts_down": ["host-three"], "hosts_unfinished": ["host-four"],
        })
        targets = find.call_args.args[0]
        self.assertEqual({(t.compute.id, t.uuids) for t in targets}, {(self.c1.id, None), (self.c2.id, None)})
        body = response.json()
        known, unknown = body["matches"]
        self.assertEqual((known["host"], known["registered"], known["vm"]), ("host-one", True, "vm-a"))
        self.assertEqual(known["url"], reverse("instances:instance", args=[self.a.id]) + "#network")
        self.assertEqual((unknown["host"], unknown["registered"], unknown["url"]), ("host-two", False, None))
        self.assertEqual((body["coverage"]["hosts_down"], body["coverage"]["hosts_unfinished"]),
                         (["host-three"], ["host-four"]))
        self.assertIn("read_at", body)

    def test_an_owner_is_scoped_to_their_vms_and_sees_no_hosts(self):
        response, find = self.search(self.owner, result={
            "matches": [row(UUID_A, "vm-a", self.c1.id), row(UUID_B, "vm-b", self.c2.id)],
            "hosts_down": ["host-two"],
        })
        (target,) = find.call_args.args[0]
        self.assertEqual((target.compute.id, target.uuids), (self.c1.id, {UUID_A}))
        body = response.json()
        self.assertEqual([m["vm"] for m in body["matches"]], ["vm-a"])
        self.assertNotIn("host", body["matches"][0])
        self.assertNotIn("hosts_down", body["coverage"])
        self.assertTrue(body["coverage"]["some_unchecked"])
        self.assertNotIn("host-two", response.content.decode())

    def test_an_owners_vm_on_two_computes_is_searched_on_both(self):
        # one UUID on two hosts: Instance is unique per compute, not per UUID
        twin = Instance.objects.create(compute=self.c2, name="vm-a-copy", uuid=UUID_A)
        UserInstance.objects.create(user=self.owner, instance=twin)
        response, find = self.search(self.owner, result={
            "matches": [row(UUID_A, "vm-a", self.c1.id), row(UUID_A, "vm-a-copy", self.c2.id)]})
        self.assertEqual({(t.compute.id, frozenset(t.uuids)) for t in find.call_args.args[0]},
                         {(self.c1.id, frozenset({UUID_A})), (self.c2.id, frozenset({UUID_A}))})
        self.assertEqual([m["url"] for m in response.json()["matches"]],
                         [reverse("instances:instance", args=[i.id]) + "#network" for i in (self.a, twin)])

    def test_a_bad_query_is_refused_without_libvirt(self):
        for q in ("", "abc", "192.0.2.300"):
            with self.subTest(q=q):
                response, find = self.search(self.admin, q=q)
                self.assertEqual(response.status_code, 400)
                self.assertIn("192.0.2.0/24", response.json()["error"])
                find.assert_not_called()

    def test_too_many_searches_answer_409(self):
        response, _ = self.search(self.admin, side_effect=addresses.Busy)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "Too many searches are still running; try again shortly.")


class FindAddressPageTests(TestCase):
    """static/js/find_address.js fills the dialog; only administrators get a Host column."""

    def page(self, user):
        self.client.force_login(user)
        return html.fromstring(self.client.get(reverse("instances:index")).content)

    def test_the_page_offers_the_search(self):
        User = get_user_model()
        for user, host_column in ((User.objects.create_superuser("fp-admin", "fp@example.com", "pw"), True),
                                  (User.objects.create_user("fp-owner", password="pw"), False)):
            with self.subTest(user=user.username):
                doc = self.page(user)
                self.assertEqual(len(doc.xpath("//button[@id='find-address-open']")), 1)
                self.assertEqual(len(doc.xpath("//div[@id='find-address']//input[@name='q']")), 1)
                headers = [" ".join(th.text_content().split()) for th in doc.xpath("//div[@id='find-address']//th")]
                self.assertEqual("Host" in headers, host_column)
