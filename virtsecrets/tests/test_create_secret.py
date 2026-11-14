"""A secret's usage goes into its XML as text, whatever it holds. Its value
is a Ceph key in base64, as `ceph auth get-key` prints it, or a password or
passphrase as typed; a new secret takes its value at once, or none, and a
value refused leaves no secret behind."""

from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from lxml import html
from virtsecrets.forms import AddSecret


class CreateSecretFormTests(SimpleTestCase):
    def test_a_password_keeps_its_spaces_and_the_flags_are_checkboxes(self):
        form = AddSecret({"usage_type": "iscsi", "usage": "iqn.2026-10.test.wvc:lun", "value": " pw ", "private": "on"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual((form.cleaned_data["value"], form.cleaned_data["ephemeral"], form.cleaned_data["private"]),
                         (" pw ", False, True))

    def test_a_usage_with_a_control_character_is_refused(self):
        # lxml refuses it in XML text (a 500); libvirt drops a line break
        # at its ends too, which stripping would hide
        for usage in ("iqn.test\x01", "a\nb", "iqn.test\n", "\tiqn.test"):
            with self.subTest(usage=usage):
                form = AddSecret({"usage_type": "iscsi", "usage": usage})
                self.assertIn("control characters", str(form.errors["usage"]))
        form = AddSecret({"usage_type": "iscsi", "usage": "   "})
        self.assertEqual(form.errors["usage"].as_data()[0].code, "required")
        form = AddSecret({"usage_type": "iscsi", "usage": " iqn.test "})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["usage"], "iqn.test")


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
