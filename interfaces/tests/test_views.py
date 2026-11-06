"""The host interface pages: creating an interface, the list, and a host
whose libvirt cannot change interfaces."""

from unittest.mock import patch

import libvirt
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from lxml import etree

from computes.models import Compute
from interfaces.tests.fakes import BASE


class CreateViewTestCase(TestCase):
    """The page validates the device against the host's devices before it
    defines an interface."""

    def test_only_a_host_device_becomes_a_bridge_member(self):
        admin = get_user_model().objects.create_superuser("iface_admin", "a@example.com", "x")
        compute = Compute.objects.create(name="iface-c", hostname="127.0.0.1:1", login="root", password="", type=1)
        self.client.force_login(admin)
        for netdev, created in (("eth9", False), ("eth0", True)):
            with self.subTest(netdev=netdev), patch("interfaces.views.wvmInterfaces") as conn_cls:
                conn = conn_cls.return_value
                conn.get_ifaces_info.return_value = []
                conn.can_change_interfaces.return_value = True
                conn.get_net_devices.return_value = ["eth0", "eth1"]
                conn.get_member_candidates.return_value = ["eth0", "eth1"]
                self.client.post(
                    reverse("interfaces", args=[compute.id]),
                    {**BASE, "netdev": netdev, "ipv6_type": "none", "create": ""},
                )
                self.assertEqual(conn.create_iface.called, created)

    def test_a_device_taken_meanwhile_is_chosen_again(self):
        # not swapped for the first device the dialog still offers
        admin = get_user_model().objects.create_superuser("iface_admin3", "c@example.com", "x")
        compute = Compute.objects.create(name="iface-c3", hostname="127.0.0.1:1", login="root", password="", type=1)
        self.client.force_login(admin)
        for select, values in (("iface_netdev", {"netdev": "eth1"}), ("iface_device", {"itype": "ethernet", "name": "eth1", "netdev": "eth0"})):
            with self.subTest(**values), patch("interfaces.views.wvmInterfaces") as conn_cls:
                conn = conn_cls.return_value
                conn.get_ifaces_info.return_value = []
                conn.can_change_interfaces.return_value = True
                conn.get_net_devices.return_value = ["eth0", "eth1"]
                conn.get_member_candidates.return_value = ["eth0"]
                page = self.client.post(reverse("interfaces", args=[compute.id]),
                                        {**BASE, **values, "ipv6_type": "none", "create": ""}).content.decode()
                self.assertFalse(conn.create_iface.called)
                chosen = etree.HTML(page).xpath(f"//select[@id='{select}']/option[@selected]/@value")
                self.assertEqual(chosen, [""])

    def test_unreadable_host_devices_are_reported_not_blamed_on_the_input(self):
        admin = get_user_model().objects.create_superuser("iface_admin2", "b@example.com", "x")
        compute = Compute.objects.create(name="iface-c2", hostname="127.0.0.1:1", login="root", password="", type=1)
        self.client.force_login(admin)
        with patch("interfaces.views.wvmInterfaces") as conn_cls:
            conn = conn_cls.return_value
            conn.get_ifaces_info.return_value = []
            conn.can_change_interfaces.return_value = True
            conn.get_net_devices.side_effect = RuntimeError("nodedev driver not running")
            response = self.client.post(
                reverse("interfaces", args=[compute.id]),
                {**BASE, "netdev": "eth0", "ipv6_type": "none", "create": ""},
            )
        self.assertFalse(conn.create_iface.called)
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("nodedev driver not running" in m for m in messages), messages)
        self.assertFalse(any("not on this host" in m for m in messages), messages)


class InterfaceListTestCase(TestCase):
    def test_the_interfaces_are_grouped_by_type(self):
        self.client.force_login(get_user_model().objects.create_superuser("iface_list", "l@example.com", "x"))
        compute = Compute.objects.create(name="iface-list", hostname="127.0.0.1:1", login="root", password="", type=1)
        ifaces = [{"name": name, "type": kind, "mac": None, "link": "up", "members": []}
                  for name, kind in (("br0", "bridge"), ("eth0", "ethernet"), ("eth1", "ethernet"))]
        with patch("interfaces.views.wvmInterfaces") as conn_cls:
            conn_cls.return_value.get_ifaces_info.return_value = ifaces
            conn_cls.return_value.can_change_interfaces.return_value = False
            page = etree.HTML(self.client.get(reverse("interfaces", args=[compute.id])).content.decode())
        # no heading for a type the host has none of
        self.assertEqual([" ".join(h.itertext()).split() for h in page.xpath("//h2")], [["Bridges", "1"], ["Ethernet", "2"]])


class UnchangeableHostTestCase(TestCase):
    """A host whose libvirt cannot change interfaces (udev backend) gets no
    create form and no start/stop/delete, only a note; posts change nothing."""

    NOTE = "only reads network interfaces"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("iface_ro", "ro@example.com", "x"))
        self.compute = Compute.objects.create(name="iface-ro", hostname="127.0.0.1:1", login="root", password="", type=1)

    def interfaces_page(self, changeable, post=None):
        with patch("interfaces.views.wvmInterfaces") as conn_cls:
            conn = conn_cls.return_value
            conn.get_ifaces_info.return_value = []
            conn.can_change_interfaces.return_value = changeable
            conn.get_net_devices.return_value = ["eth0", "eth1"]
            url = reverse("interfaces", args=[self.compute.id])
            response = self.client.post(url, post) if post else self.client.get(url)
        return conn, response.content.decode()

    def test_the_interfaces_page_offers_create_only_where_it_works(self):
        for changeable in (True, False):
            with self.subTest(changeable=changeable):
                conn, page = self.interfaces_page(changeable)
                self.assertEqual("#AddInterface" in page, changeable)
                self.assertEqual(self.NOTE in page, not changeable)
                # the devices are only the form's choices
                self.assertEqual(conn.get_net_devices.called, changeable)

    def test_a_create_post_creates_nothing(self):
        conn, page = self.interfaces_page(False, {**BASE, "netdev": "eth1", "ipv6_type": "none", "create": ""})
        conn.create_iface.assert_not_called()
        self.assertIn(self.NOTE, page)

    def interface_page(self, changeable, state, post=None):
        with patch("interfaces.views.wvmInterface") as conn_cls:
            conn = conn_cls.return_value
            conn.can_change_interfaces.return_value = changeable
            conn.is_active.return_value = state
            url = reverse("interface", args=[self.compute.id, "br0"])
            response = self.client.post(url, post) if post else self.client.get(url)
        return conn, response

    def test_the_interface_page_shows_the_state_without_actions(self):
        # libvirt's own state is told where it manages the interface only; the link always
        for state in (1, 0):
            with self.subTest(state=state):
                conn, response = self.interface_page(False, state)
                page = response.content.decode()
                self.assertNotIn('name="start"', page)
                self.assertNotIn('name="stop"', page)
                self.assertNotIn(">Active<", page)
                self.assertIn(self.NOTE, page)
        _conn, response = self.interface_page(True, 0)
        page = response.content.decode()
        self.assertIn('name="start"', page)
        self.assertIn(">Inactive<", page)

    def test_a_host_that_could_not_be_read_offers_nothing(self):
        # not knowing whether the host can change interfaces is not a yes
        with patch("interfaces.views.wvmInterface", side_effect=libvirt.libvirtError("unreachable")):
            page = self.client.get(reverse("interface", args=[self.compute.id, "br0"])).content.decode()
        self.assertNotIn(self.NOTE, page)
        self.assertNotIn("Interface start/stop/delete form", page)

    def test_start_stop_and_delete_posts_change_nothing(self):
        for action in ("start", "stop", "delete"):
            with self.subTest(action=action):
                conn, response = self.interface_page(False, 1, {action: ""})
                self.assertEqual(response.status_code, 200)
                for method in (conn.start_iface, conn.stop_iface, conn.delete_iface):
                    method.assert_not_called()
