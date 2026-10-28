"""A filter is changed by defining it again with its own UUID, which libvirt
does in place, also while a running VM uses it (undefining one in use is
refused). A definition libvirt refuses is reported, not undone by an undefine
and another define. libvirt's test driver has no filters, so the connection
is a mock."""

from unittest.mock import MagicMock, patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from libvirt import libvirtError
from lxml import etree, html
from vrtManager.nwfilters import element_text

UUID = "6d1f7a10-0000-4000-8000-00000000c0de"
XML = (f"<filter name='web' chain='root'><uuid>{UUID}</uuid><filterref filter='clean-traffic'/>"
       "<rule action='accept' direction='in' priority='500'><tcp dstportstart='22'/></rule>"
       "<rule action='drop' direction='in' priority='900'><all/></rule></filter>")


def text(xml, tag, index):
    """The text the page sends back for the tag element at index."""
    return element_text(etree.fromstring(xml).findall(tag)[index])


class FilterRedefineTests(TestCase):
    def setUp(self):
        patcher = patch("vrtManager.connection.connection_manager.get_connection")
        self.wvm = patcher.start().return_value
        self.addCleanup(patcher.stop)
        nwfilter = self.wvm.nwfilterLookupByName.return_value
        nwfilter.XMLDesc.return_value = XML
        nwfilter.name.return_value = "web"
        nwfilter.UUIDString.return_value = UUID
        self.wvm.listNWFilters.return_value = ["web", "clean-traffic", "no-spoofing"]
        compute = Compute.objects.create(name="nwf", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("nwf", "nwf@example.com", "pw"))
        self.url = reverse("nwfilter", args=[compute.id, "web"])
        self.list_url = reverse("nwfilters", args=[compute.id])

    def defined(self, data):
        response = self.client.post(self.url, data)
        self.wvm.nwfilterLookupByName.return_value.undefine.assert_not_called()
        self.wvm.nwfilterDefineXML.assert_called_once()
        return etree.fromstring(self.wvm.nwfilterDefineXML.call_args.args[0]), response

    def test_a_rule_is_removed_in_place(self):
        tree, _ = self.defined({"del_nwfilter_rule": "", "index": "1", "rule": text(XML, "rule", 1)})
        self.assertEqual(tree.findtext("uuid"), UUID)
        self.assertEqual([r.get("action") for r in tree.findall("rule")], ["accept"])

    def test_a_reference_is_removed_in_place(self):
        tree, _ = self.defined({"del_nwfilter_ref": "", "index": "0", "ref": text(XML, "filterref", 0)})
        self.assertEqual((tree.findtext("uuid"), tree.findall("filterref")), (UUID, []))

    def test_a_rule_is_added_in_place(self):
        rule = "<rule action='accept' direction='in' priority='500'><udp dstportstart='53'/></rule>"
        tree, response = self.defined({"add_nwfilter_rule": "", "nwfilterrule_xml": rule})
        self.assertEqual(tree.findtext("uuid"), UUID)
        # a rule of its own: libvirt keeps one protocol per rule
        self.assertEqual([rule.xpath("*/@dstportstart") for rule in tree.findall("rule")], [["22"], [], ["53"]])
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

    def test_one_change_a_post(self):
        # two at once would both start from the page's reading, the second undoing the first
        rule = "<rule action='accept' direction='in' priority='500'><udp dstportstart='53'/></rule>"
        self.defined({"add_nwfilter_rule": "", "nwfilterrule_xml": rule, "add_nwfilter_ref": "", "nwfilters_select": "no-spoofing"})

    def test_a_post_for_a_filter_gone_meanwhile_goes_to_the_list(self):
        self.wvm.nwfilterLookupByName.side_effect = libvirtError("Network filter not found")
        response = self.client.post(self.url, {"del_nwfilter_rule": "", "index": "0", "rule": ""})
        self.assertRedirects(response, self.list_url, fetch_redirect_response=False)
        self.wvm.nwfilterDefineXML.assert_not_called()

    def test_a_refused_definition_is_reported_not_undone(self):
        self.wvm.nwfilterDefineXML.side_effect = libvirtError("XML error: Invalid value for attribute 'action'")
        _, response = self.defined({"del_nwfilter_rule": "", "index": "1", "rule": text(XML, "rule", 1)})
        self.assertIn("Invalid value for attribute 'action'", " ".join(str(m) for m in get_messages(response.wsgi_request)))


ALIKE = (f"<filter name='web' chain='root'><uuid>{UUID}</uuid>"
         "<rule action='accept' direction='in' priority='500'><tcp dstportstart='22'/></rule>"
         "<rule action='accept' direction='in' priority='500'><tcp dstportstart='80'/></rule></filter>")


class RuleDeleteTests(TestCase):
    """Rules sharing action, direction and priority: the one clicked goes,
    and only while it reads as the page showed it."""

    def setUp(self):
        patcher = patch("vrtManager.connection.connection_manager.get_connection")
        self.wvm = patcher.start().return_value
        self.addCleanup(patcher.stop)
        nwfilter = self.wvm.nwfilterLookupByName.return_value
        nwfilter.XMLDesc.return_value = ALIKE
        nwfilter.name.return_value = "web"
        nwfilter.UUIDString.return_value = UUID
        compute = Compute.objects.create(name="nwf", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("nwf", "nwf@example.com", "pw"))
        self.url = reverse("nwfilter", args=[compute.id, "web"])

    def delete(self, index, rule):
        return self.client.post(self.url, {"del_nwfilter_rule": "", "index": index, "rule": rule})

    def test_the_second_of_two_alike_rules_is_deleted(self):
        # sent back by a browser, with other line breaks between its tags
        self.delete("1", text(ALIKE, "rule", 1).replace("><", ">\r\n  <"))
        tree = etree.fromstring(self.wvm.nwfilterDefineXML.call_args.args[0])
        self.assertEqual(tree.xpath("rule/*/@dstportstart"), ["22"])

    def test_a_rule_that_is_no_longer_there_is_not_deleted(self):
        # gone, another one at its place (reordered), or not an index
        for index, rule in (("2", text(ALIKE, "rule", 1)), ("0", text(ALIKE, "rule", 1)),
                            ("-1", text(ALIKE, "rule", 1)), ("x", text(ALIKE, "rule", 0)),
                            ("²", text(ALIKE, "rule", 0)), ("9" * 5000, text(ALIKE, "rule", 0))):
            with self.subTest(index=index):
                response = self.delete(index, rule)
                self.assertIn("reload the page", " ".join(str(m) for m in get_messages(response.wsgi_request)))
        self.wvm.nwfilterDefineXML.assert_not_called()


class PageTests(TestCase):
    """The list says what uses each filter, and does not offer to delete one in
    use; a filter's page links the VMs that use it and shows its references'
    parameters."""

    def setUp(self):
        patcher = patch("vrtManager.connection.connection_manager.get_connection")
        self.wvm = patcher.start().return_value
        self.addCleanup(patcher.stop)
        nwfilter = self.wvm.nwfilterLookupByName.return_value
        nwfilter.XMLDesc.return_value = XML.replace("<filterref filter='clean-traffic'/>",
                                                    "<filterref filter='clean-traffic'><parameter name='IP' value='192.0.2.10'/></filterref>")
        nwfilter.name.return_value = "web"
        nwfilter.UUIDString.return_value = UUID
        self.wvm.listAllNWFilters.return_value = [nwfilter]
        self.wvm.listNWFilters.return_value = ["web", "clean-traffic"]
        vm = MagicMock(**{"name.return_value": "web-1", "isActive.return_value": False, "XMLDesc.return_value":
                          "<domain><devices><interface type='network'><filterref filter='web'/></interface></devices></domain>"})
        self.wvm.listAllDomains.return_value = [vm]
        self.compute = Compute.objects.create(name="nwf", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("nwf", "nwf@example.com", "pw"))

    def test_a_filter_in_use_is_not_offered_for_delete(self):
        page = html.fromstring(self.client.get(reverse("nwfilters", args=[self.compute.id])).content)
        [delete] = page.xpath("//button[@name='del_nwfilter']")
        self.assertIsNotNone(delete.get("disabled"))
        self.assertIn("1 VM", page.xpath("//tbody/tr/td[6]")[0].text_content())

    def test_the_filter_page_links_its_vms_and_shows_parameters(self):
        instance = Instance.objects.create(compute=self.compute, name="web-1", uuid="6d1f7a10-0000-4000-8000-00000000a001")
        page = html.fromstring(self.client.get(reverse("nwfilter", args=[self.compute.id, "web"])).content)
        self.assertEqual(page.xpath("//a[text()='web-1']/@href"), [reverse("instances:instance", args=[instance.id])])
        self.assertIn("IP=192.0.2.10", page.text_content())

    def test_without_the_vms_the_list_is_not_shown(self):
        # it would offer to delete filters in use
        self.wvm.listAllDomains.side_effect = libvirtError("connection reset")
        page = html.fromstring(self.client.get(reverse("nwfilters", args=[self.compute.id])).content)
        self.assertEqual(page.xpath("//button[@name='del_nwfilter']"), [])

    def test_a_reference_to_a_filter_gone_is_not_a_link(self):
        self.wvm.listNWFilters.return_value = ["web"]
        page = html.fromstring(self.client.get(reverse("nwfilter", args=[self.compute.id, "web"])).content)
        self.assertEqual(page.xpath("//a[text()='clean-traffic']"), [])
        self.assertIn("Missing", page.xpath("//td[contains(., 'clean-traffic')]")[0].text_content())
