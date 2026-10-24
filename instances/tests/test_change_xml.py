from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from libvirt import libvirtError
from vrtManager.instance import PERSISTENT_XML
from logs.models import Logs

CURRENT = "<domain>\n  <name>xml-vm</name>\n  <memory>1024</memory>\n</domain>"
LIVE = "<domain id='3'>\n  <name>xml-vm</name>\n  <memory>512</memory>\n</domain>"
EDITED = "<domain>\n  <name>xml-vm</name>\n  <memory>2048</memory>\n</domain>"


class ChangeXmlTestCase(TestCase):
    """The XML editor shows what a change does before it is saved, and saves
    only over the definition it was opened with: the persistent one, which a
    running VM uses at its next start."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("xml_admin", "x@example.com", "pw"))
        compute = Compute.objects.create(name="xml-compute", hostname="127.0.0.1", login="", password="", type=4)
        self.instance = Instance.objects.create(compute=compute, name="xml-vm", uuid="11111111-2222-3333-4444-888888888888")

    def post(self, status=5, xml=EDITED, base=CURRENT, confirm=False, define_error=None):
        data = {"inst_xml": xml, "base": base}
        if confirm:
            data["confirm"] = "1"
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.get_status.return_value = status
            wvm.return_value._XMLDesc.side_effect = lambda flags: CURRENT if flags == PERSISTENT_XML else LIVE
            wvm.return_value._defineXML.side_effect = define_error
            response = self.client.post(reverse("instances:change_xml", args=[self.instance.id]), data)
        return response, wvm.return_value._defineXML

    def test_without_confirm_the_change_is_shown_not_saved(self):
        response, define = self.post()
        define.assert_not_called()
        diff = response.json()["diff"]
        self.assertIn("-  <memory>1024</memory>", diff)
        self.assertIn("+  <memory>2048</memory>", diff)

    def test_an_unchanged_definition_shows_no_difference(self):
        response, _ = self.post(xml=CURRENT)
        self.assertEqual(response.json()["diff"], [])

    def test_a_confirmed_change_is_saved_and_logged(self):
        response, define = self.post(confirm=True)
        define.assert_called_once_with(EDITED)
        self.assertEqual(response.json(), {"saved": True})
        self.assertIn("XML", " ".join(str(m) for m in get_messages(response.wsgi_request)))
        row = Logs.objects.get(instance_uuid=self.instance.uuid)
        self.assertEqual((row.message, row.success), ("VM xml-vm: change XML", True))

    def test_a_definition_changed_since_the_editor_opened_is_not_overwritten(self):
        for confirm in (False, True):
            with self.subTest(confirm=confirm):
                response, define = self.post(base="<domain>older</domain>", confirm=confirm)
                define.assert_not_called()
                self.assertEqual(response.status_code, 409)
                self.assertIn("changed since", response.json()["error"])

    def test_a_definition_libvirt_refuses_comes_back_with_the_reason(self):
        response, define = self.post(confirm=True, define_error=libvirtError("unsupported configuration: bad memory"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("bad memory", response.json()["error"])
        row = Logs.objects.get(instance_uuid=self.instance.uuid)
        self.assertEqual((row.message, row.success), ("VM xml-vm: change XML: unsupported configuration: bad memory", False))

    def test_a_running_or_paused_vm_gets_the_definition_for_its_next_start(self):
        for status in (1, 3):
            with self.subTest(status=status):
                response, define = self.post(status, confirm=True)
                define.assert_called_once_with(EDITED)
                self.assertIn("next start", " ".join(str(m) for m in get_messages(response.wsgi_request)))

    def test_the_line_breaks_a_form_posts_are_the_same_definition(self):
        response, _ = self.post(base=CURRENT.replace("\n", "\r\n"))
        self.assertEqual(response.status_code, 200)

    def test_an_empty_definition_is_refused(self):
        response, define = self.post(xml="  ", confirm=True)
        define.assert_not_called()
        self.assertEqual(response.status_code, 400)
