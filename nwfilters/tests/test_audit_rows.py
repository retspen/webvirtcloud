"""Network filter changes write rows on the Logs page. libvirt's test driver
has no filters, so the connection is a mock (as in test_redefine.py)."""

from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from libvirt import libvirtError

from logs.models import Logs

UUID = "6d1f7a10-0000-4000-8000-00000000c0de"
XML = (f"<filter name='web' chain='root'><uuid>{UUID}</uuid><filterref filter='clean-traffic'/>"
       "<rule action='drop' direction='in' priority='900'><all/></rule></filter>")
NEW = "<filter name='f1' chain='root'><uuid>6d1f7a10-0000-4000-8000-0000000000f1</uuid></filter>"


def rows():
    return list(Logs.objects.order_by("id").values_list("message", "success"))


class FilterRowTests(TestCase):
    def setUp(self):
        patcher = patch("vrtManager.connection.connection_manager.get_connection")
        self.wvm = patcher.start().return_value
        self.addCleanup(patcher.stop)
        nwfilter = self.wvm.nwfilterLookupByName.return_value
        nwfilter.XMLDesc.return_value = XML
        nwfilter.name.return_value = "web"
        nwfilter.UUIDString.return_value = UUID
        self.wvm.listNWFilters.return_value = ["web"]
        self.compute = Compute.objects.create(name="c1", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("audit-admin", "a@example.com", "pw"))
        Logs.objects.all().delete()  # the login's row
        self.list_url = reverse("nwfilters", args=[self.compute.id])
        self.url = reverse("nwfilter", args=[self.compute.id, "web"])

    @patch("nwfilters.views.wvmInstances")
    def test_filter_list_actions(self, instances):
        instances.return_value.get_instances.return_value = []
        # the list is read again, so the new filter shows
        self.assertRedirects(self.client.post(self.list_url, {"create_nwfilter": "", "nwfilter_xml": NEW}),
                             self.list_url, fetch_redirect_response=False)
        self.client.post(self.list_url, {"cln_nwfilter": "", "nwfiltername": "web", "cln_name": "web-copy"})
        self.client.post(self.list_url, {"del_nwfilter": "", "nwfiltername": "web"})
        self.assertEqual(rows(), [
            ("Network filter f1: add", True),
            ("Network filter web: clone as web-copy", True),
            ("Network filter web: delete", True),
        ])
        self.assertEqual(set(Logs.objects.values_list("host", flat=True)), {"c1"})

    def test_a_duplicate_filter_is_a_failed_row(self):
        response = self.client.post(self.list_url, {"create_nwfilter": "", "nwfilter_xml": XML})
        self.assertIn("A network filter with this name already exists",
                      [str(m) for m in get_messages(response.wsgi_request)])
        other = XML.replace("name='web'", "name='other'")
        self.client.post(self.list_url, {"create_nwfilter": "", "nwfilter_xml": other})
        self.wvm.nwfilterDefineXML.assert_not_called()
        self.assertEqual(rows(), [
            ("Network filter web: add: name already in use", False),
            ("Network filter other: add: UUID already in use", False),
        ])

    def test_an_unparsable_filter(self):
        self.wvm.nwfilterDefineXML.side_effect = libvirtError("XML error")
        response = self.client.post(self.list_url, {"create_nwfilter": "", "nwfilter_xml": "<filter"})
        self.assertEqual(response.status_code, 200)
        [(message, success)] = rows()
        self.assertFalse(success)
        self.assertTrue(message.startswith("Network filter (no name): add: "), message)

    @patch("nwfilters.views.wvmInstance")
    @patch("nwfilters.views.wvmInstances")
    def test_a_filter_in_use_is_not_deleted(self, instances, instance):
        instances.return_value.get_instances.return_value = ["web-1"]
        instance.return_value.get_filterrefs.return_value = ["web"]
        self.client.post(self.list_url, {"del_nwfilter": "", "nwfiltername": "web"})
        self.wvm.nwfilterLookupByName.return_value.undefine.assert_not_called()
        self.assertEqual(rows(), [("Network filter web: delete: in use by web-1", False)])

    def test_filter_page_actions(self):
        self.client.post(self.url, {"edit_nwfilter": "", "edit_xml": XML})
        self.client.post(self.url, {"add_nwfilter_rule": "",
                                    "nwfilterrule_xml": "<rule action='accept' direction='in' priority='500'><all/></rule>"})
        self.client.post(self.url, {"del_nwfilter_rule": "", "index": "0", "action": "drop", "direction": "in", "priority": "900"})
        self.client.post(self.url, {"add_nwfilter_ref": "", "nwfilters_select": "no-spoofing"})
        self.client.post(self.url, {"del_nwfilter_ref": "", "ref": "clean-traffic"})
        self.assertEqual(rows(), [
            ("Network filter web: change XML", True),
            ("Network filter web: add rule", True),
            ("Network filter web: delete rule", True),
            ("Network filter web: add reference no-spoofing", True),
            ("Network filter web: delete reference clean-traffic", True),
        ])
        self.assertFalse(Logs.objects.filter(message__contains="<").exists())

    def test_a_failing_rule_add(self):
        self.wvm.nwfilterDefineXML.side_effect = libvirtError("refused")
        response = self.client.post(self.url, {"add_nwfilter_rule": "", "nwfilterrule_xml": "<rule action='accept' direction='in' priority='500'><all/></rule>"})
        self.assertIn("refused", " ".join(str(m) for m in get_messages(response.wsgi_request)))
        [(message, success)] = rows()
        self.assertFalse(success)
        self.assertTrue(message.startswith("Network filter web: add rule: "), message)
