"""The VM lists follow libvirt: instances:states gives the states of the
listed VMs, read in one call per host; vm_states.js polls it and reloads the
list when an answer differs from the one before. A user who does not see
hosts gets only the hosts and VMs of their own."""

import json
from unittest.mock import MagicMock, PropertyMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from libvirt import libvirtError
from lxml import html

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance

UP = {"aaaaaaaa-0000-4000-8000-000000000001": ["web", 1], "aaaaaaaa-0000-4000-8000-000000000002": ["db", 5]}


class VmStatesTestCase(TestCase):
    def setUp(self):
        self.up = Compute.objects.create(name="up", hostname="192.0.2.70", login="u", password="p", type=1)
        self.down = Compute.objects.create(name="down", hostname="192.0.2.71", login="u", password="p", type=1)
        self.web = Instance.objects.create(compute=self.up, name="web", uuid="aaaaaaaa-0000-4000-8000-000000000001")
        self.admin = get_user_model().objects.create_superuser("st-admin", "st@example.com", "pw")

    def get(self, user, query="", read=lambda: dict(UP)):
        self.client.force_login(user)
        proxy = MagicMock()
        proxy.get_domain_states.side_effect = read
        # self.up answers, self.down cannot be reached
        with patch.object(Compute, "status", property(lambda c: c.pk == self.up.pk)), \
                patch.object(Compute, "proxy", new_callable=PropertyMock, return_value=proxy):
            return self.client.get(reverse("instances:states") + query)

    def test_an_administrator_gets_every_host_and_a_host_that_cannot_be_read(self):
        response = self.get(self.admin)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response.json()["computes"], {str(self.up.pk): {"ok": True, "vms": UP},
                                                       str(self.down.pk): {"ok": False}})

    def test_a_host_whose_listing_fails_cannot_be_read(self):
        def fails():
            raise libvirtError("Cannot recv data")
        self.assertEqual(self.get(self.admin, read=fails).json()["computes"][str(self.up.pk)], {"ok": False})

    def test_a_user_gets_the_hosts_and_vms_of_their_own(self):
        owner = get_user_model().objects.create_user("st-owner", password="pw")
        UserInstance.objects.create(user=owner, instance=self.web)
        self.assertEqual(self.get(owner).json()["computes"],
                         {str(self.up.pk): {"ok": True, "vms": {self.web.uuid: ["web", 1]}}})
        stranger = get_user_model().objects.create_user("st-stranger", password="pw")
        self.assertEqual(self.get(stranger).json()["computes"], {})

    def test_one_host_s_list_is_for_administrators(self):
        self.assertEqual(self.get(self.admin, f"?compute={self.up.pk}").json()["computes"],
                         {str(self.up.pk): {"ok": True, "vms": UP}})
        owner = get_user_model().objects.create_user("st-owner2", password="pw")
        self.assertEqual(self.get(owner, f"?compute={self.up.pk}").status_code, 403)

    def test_a_user_s_uuid_on_another_host_is_not_theirs(self):
        # one UUID may be defined on two hosts: a VM is its host and UUID
        other = Compute.objects.create(name="other", hostname="192.0.2.72", login="u", password="p", type=1)
        Instance.objects.create(compute=other, name="mine-too", uuid="aaaaaaaa-0000-4000-8000-000000000009")
        owner = get_user_model().objects.create_user("st-owner3", password="pw")
        UserInstance.objects.create(user=owner, instance=self.web)
        UserInstance.objects.create(user=owner, instance=Instance.objects.get(name="mine-too"))
        self.client.force_login(owner)
        proxy = MagicMock()
        proxy.get_domain_states.return_value = dict(UP)  # both hosts list the same UUIDs
        with patch.object(Compute, "status", True), \
                patch.object(Compute, "proxy", new_callable=PropertyMock, return_value=proxy):
            computes = self.client.get(reverse("instances:states")).json()["computes"]
        self.assertEqual(computes, {str(self.up.pk): {"ok": True, "vms": {self.web.uuid: ["web", 1]}},
                                    str(other.pk): {"ok": True, "vms": {}}})

    def test_the_lists_poll_it(self):
        self.client.force_login(self.admin)
        with patch.object(Compute, "status", property(lambda c: c.pk == self.up.pk)), \
                patch.object(Compute, "proxy", new_callable=PropertyMock, return_value=MagicMock()), \
                patch("instances.views.utils.refr"), patch("computes.views.utils.refresh_instance_database"), \
                patch.object(Instance, "proxy", new_callable=PropertyMock, return_value=MagicMock()):
            for url, states_url in ((reverse("instances:index"), reverse("instances:states")),
                                    (reverse("instances", args=[self.up.pk]),
                                     reverse("instances:states") + f"?compute={self.up.pk}")):
                with self.subTest(url=url):
                    page = html.fromstring(self.client.get(url).content)
                    self.assertEqual(json.loads(page.get_element_by_id("vm-states-url").text), states_url)
