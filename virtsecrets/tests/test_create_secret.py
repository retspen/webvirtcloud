"""A secret's usage goes into its XML as text, whatever it holds. Its value
is a Ceph key in base64, as `ceph auth get-key` prints it, or a password or
passphrase as typed; a new secret takes its value at once, or none, and a
value refused leaves no secret behind."""

from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from lxml import etree, html
from virtsecrets.forms import AddSecret
from vrtManager.util import OperationError
from vrtManager.virtsecrets import wvmSecrets


def connection():
    with patch("vrtManager.connection.connection_manager.get_connection") as get:
        conn = wvmSecrets("host", "login", "pw", 1)
    return conn, get.return_value


class CreateSecretTests(SimpleTestCase):
    def test_the_usage_is_text_of_its_element(self):
        for usage_type, element, usage in (
            ("volume", "volume", "/var/lib/libvirt/images/vm-1.qcow2"),
            ("iscsi", "target", "iqn.2026-10.test.wvc:lun"),
            ("ceph", "name", "client.libvirt secret"),
            ("tls", "name", "migration"),
            ("vtpm", "name", "VM web-1's vTPM"),
            ("volume", "volume", "/a'b<c>&d\""),
        ):
            with self.subTest(usage_type=usage_type, usage=usage):
                conn, wvm = connection()
                conn.create_secret(usage_type, usage, private=True)
                secret = etree.fromstring(wvm.secretDefineXML.call_args.args[0])
                self.assertEqual((secret.get("ephemeral"), secret.get("private")), ("no", "yes"))
                self.assertEqual(secret.find("usage").get("type"), usage_type)
                self.assertEqual(secret.findtext(f"usage/{element}"), usage)
                wvm.secretDefineXML.return_value.setValue.assert_not_called()

    def test_a_new_secret_takes_its_value_at_once(self):
        for usage_type, value, stored in (("ceph", "cHcA/w==", b"pw\x00\xff"), ("iscsi", " pass word ", b" pass word ")):
            with self.subTest(usage_type=usage_type):
                conn, wvm = connection()
                conn.create_secret(usage_type, "lun", value)
                wvm.secretDefineXML.return_value.setValue.assert_called_once_with(stored)

    def test_a_value_refused_leaves_no_secret(self):
        conn, wvm = connection()
        with self.assertRaisesRegex(OperationError, "base64"):
            conn.create_secret("ceph", "client.libvirt", "not base64!")
        wvm.secretDefineXML.assert_not_called()
        wvm.secretDefineXML.return_value.setValue.side_effect = libvirt.libvirtError("refused")
        with self.assertRaises(libvirt.libvirtError):
            conn.create_secret("iscsi", "lun", "pw")
        wvm.secretDefineXML.return_value.undefine.assert_called_once_with()


class SecretValueTests(SimpleTestCase):
    def set_value(self, usage_type, value):
        conn, wvm = connection()
        secret = wvm.secretLookupByUUIDString.return_value
        secret.XMLDesc.return_value = f"<secret><usage type='{usage_type}'><name>x</name></usage></secret>"
        conn.set_secret_value("uuid", value)
        return secret.setValue

    def test_a_ceph_key_is_stored_as_its_bytes_a_password_as_typed(self):
        self.set_value("ceph", "cHcA/w==").assert_called_once_with(b"pw\x00\xff")
        # a password that happens to be base64 is not decoded
        self.set_value("iscsi", "cHcA/w==").assert_called_once_with(b"cHcA/w==")
        self.set_value("vtpm", " pässword ").assert_called_once_with(" pässword ".encode())

    def test_a_ceph_key_that_is_not_base64_is_refused_without_the_value(self):
        for value in ("b'cHc='", "not base64!", "kéy"):
            with self.subTest(value=value), self.assertRaises(OperationError) as refused:
                self.set_value("ceph", value)
            self.assertNotIn(value, str(refused.exception))


class CreateSecretFormTests(SimpleTestCase):
    def test_a_password_keeps_its_spaces_and_the_flags_are_checkboxes(self):
        form = AddSecret({"usage_type": "iscsi", "usage": "iqn.2026-10.test.wvc:lun", "value": " pw ", "private": "on"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual((form.cleaned_data["value"], form.cleaned_data["ephemeral"], form.cleaned_data["private"]),
                         (" pw ", False, True))


class CreateSecretDialogTests(TestCase):
    def test_the_dialog_offers_the_usage_types_the_form_takes(self):
        compute = Compute.objects.create(name="secret-usage", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("usage", "usage@example.com", "pw"))
        with patch("virtsecrets.views.wvmSecrets") as conn:
            conn.return_value.get_secrets_info.return_value = []
            conn.return_value.get_users.return_value = {}
            response = self.client.get(reverse("virtsecrets", args=[compute.id]))
        offered = html.fromstring(response.content).xpath("//select[@id='secret_usage_type']/option/@value")
        self.assertEqual(offered, [value for value, _ in AddSecret.base_fields["usage_type"].choices])
