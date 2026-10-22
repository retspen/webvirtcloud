"""A filter is changed by defining it again with its own UUID, which libvirt
does in place, also while a running VM uses it (undefining one in use is
refused). A definition libvirt refuses is reported, not undone by an undefine
and another define. libvirt's test driver has no filters, so the connection
is a mock."""

from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from libvirt import libvirtError
from lxml import etree, html

UUID = "6d1f7a10-0000-4000-8000-00000000c0de"
XML = (f"<filter name='web' chain='root'><uuid>{UUID}</uuid><filterref filter='clean-traffic'/>"
       "<rule action='accept' direction='in' priority='500'><tcp dstportstart='22'/></rule>"
       "<rule action='drop' direction='in' priority='900'><all/></rule></filter>")


class FilterRedefineTests(TestCase):
    def setUp(self):
        patcher = patch("vrtManager.connection.connection_manager.get_connection")
        self.wvm = patcher.start().return_value
        self.addCleanup(patcher.stop)
        nwfilter = self.wvm.nwfilterLookupByName.return_value
        nwfilter.XMLDesc.return_value = XML
        nwfilter.name.return_value = "web"
        nwfilter.UUIDString.return_value = UUID
        self.wvm.listNWFilters.return_value = ["web"]
        compute = Compute.objects.create(name="nwf", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("nwf", "nwf@example.com", "pw"))
        self.url = reverse("nwfilter", args=[compute.id, "web"])

    def defined(self, data):
        response = self.client.post(self.url, data)
        self.wvm.nwfilterLookupByName.return_value.undefine.assert_not_called()
        self.wvm.nwfilterDefineXML.assert_called_once()
        return etree.fromstring(self.wvm.nwfilterDefineXML.call_args.args[0]), response

    def test_a_rule_is_removed_in_place(self):
        tree, _ = self.defined({"del_nwfilter_rule": "", "action": "drop", "direction": "in", "priority": "900"})
        self.assertEqual(tree.findtext("uuid"), UUID)
        self.assertEqual([r.get("action") for r in tree.findall("rule")], ["accept"])

    def test_a_reference_is_removed_in_place(self):
        tree, _ = self.defined({"del_nwfilter_ref": "", "ref": "clean-traffic"})
        self.assertEqual((tree.findtext("uuid"), tree.findall("filterref")), (UUID, []))

    def test_a_rule_is_added_in_place(self):
        rule = "<rule action='accept' direction='in' priority='500'><udp dstportstart='53'/></rule>"
        tree, response = self.defined({"add_nwfilter_rule": "", "nwfilterrule_xml": rule})
        self.assertEqual(tree.findtext("uuid"), UUID)
        self.assertEqual(tree.xpath("rule[@priority='500']/*/@dstportstart"), ["22", "53"])
        self.assertRedirects(response, self.url, fetch_redirect_response=False)

    def test_a_reference_is_added_in_place(self):
        tree, response = self.defined({"add_nwfilter_ref": "", "nwfilters_select": "no-spoofing"})
        self.assertEqual(tree.findtext("uuid"), UUID)
        self.assertEqual(tree.xpath("filterref/@filter"), ["clean-traffic", "no-spoofing"])
        self.assertRedirects(response, self.url, fetch_redirect_response=False)

    def test_the_editor_holds_the_uuid_and_saves_in_place(self):
        page = html.fromstring(self.client.get(self.url).content)
        edited = page.get_element_by_id("edit_editor").text
        self.assertIn(UUID, edited)
        tree, _ = self.defined({"edit_nwfilter": "", "edit_xml": edited})
        self.assertEqual(tree.findtext("uuid"), UUID)

    def test_a_refused_definition_is_reported_not_undone(self):
        self.wvm.nwfilterDefineXML.side_effect = libvirtError("XML error: Invalid value for attribute 'action'")
        _, response = self.defined({"del_nwfilter_rule": "", "action": "drop", "direction": "in", "priority": "900"})
        self.assertIn("Invalid value for attribute 'action'", " ".join(str(m) for m in get_messages(response.wsgi_request)))
