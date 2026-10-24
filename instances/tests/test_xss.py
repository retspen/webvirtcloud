"""
JSON endpoints must not be served as text/html (reflected XSS), and
templates must not build HTML by concatenating server data that contains
user-controlled names (stored XSS).
"""
import re
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserInstance, UserSSHKey
from computes.models import Compute
from instances.models import Instance

ROOT = Path(__file__).resolve().parent.parent.parent
PAYLOAD = "<script>alert(1)</script>"


class JsonEndpointContentTypeTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="xss_super", email="xss_super@example.com", password="password"
        )
        self.compute = Compute.objects.create(
            name="xss-compute", hostname="127.0.0.1", login="root", password="", type=1
        )
        self.instance = Instance.objects.create(
            compute=self.compute,
            name="xss-vm",
            uuid="99999999-8888-7777-6666-555555555555",
        )
        UserInstance.objects.create(instance=self.instance, user=self.superuser)
        UserSSHKey.objects.create(
            user=self.superuser,
            keyname="k",
            keypublic=f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI {PAYLOAD}",
        )
        self.client.force_login(self.superuser)

    def assertJson(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_guess_mac_address_reflects_vname_as_json(self):
        res = self.client.get(
            reverse("instances:guess_mac_address", args=["<img src=x onerror=alert(1)>"])
        )
        self.assertJson(res)

    def test_random_mac_address_is_json(self):
        self.assertJson(self.client.get(reverse("instances:random_mac_address")))

    def test_guess_clone_name_is_json(self):
        self.assertJson(self.client.get(reverse("instances:guess_clone_name")))

    def test_sshkeys_is_json(self):
        self.assertJson(
            self.client.get(reverse("instances:sshkeys", args=[self.instance.id]))
        )

    def test_sshkeys_plain_is_text_plain(self):
        res = self.client.get(
            reverse("instances:sshkeys", args=[self.instance.id]) + "?plain=true"
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res["Content-Type"].startswith("text/plain"))

    def test_storage_volumes_is_json(self):
        with patch("storages.views.wvmStorage") as mock_storage:
            mock_storage.return_value.get_volumes.return_value = [PAYLOAD]
            res = self.client.get(
                reverse("volumes", args=[self.compute.id, "default"])
            )
        self.assertJson(res)

    def test_datasource_metadata_is_json(self):
        self.assertJson(
            self.client.get(reverse("ds_openstack_metadata", args=["latest"]))
        )

    def test_compute_json_endpoints_are_json(self):
        urls = [
            reverse("compute_graph", args=[self.compute.id]),
            reverse("machines", args=[self.compute.id, "x86_64"]),
            reverse("buses", args=[self.compute.id, "x86_64", "q35", "disk"]),
        ]
        with patch("computes.views.ComputeManager") as mock_mgr:
            for method in ("compute_graph", "get_machine_types", "get_disk_buses"):
                getattr(mock_mgr.return_value, method).return_value = "{}"
            for url in urls:
                with self.subTest(url=url):
                    self.assertJson(self.client.get(url))

    def test_vm_logs_is_json(self):
        self.assertJson(self.client.get(reverse("vm_logs", args=[self.instance.pk])))


class TemplateHtmlConcatenationTestCase(TestCase):
    """
    The log table and the volume dropdown are filled by JavaScript from JSON
    that contains user-entered names. They must use DOM APIs (.text()/.val())
    instead of concatenating the values into an HTML string.
    """

    def _read(self, relative):
        return (ROOT / relative).read_text()

    def test_logs_table_does_not_concatenate_log_fields_into_html(self):
        src = self._read("instances/templates/instances/stats_tab.html")
        for field in ("date", "user", "message"):
            self.assertNotIn(f"+row['{field}']+", src)
        self.assertNotIn('$("#logs_table > tbody").html(', src)

    def test_volume_dropdown_does_not_concatenate_volume_names_into_html(self):
        src = self._read("instances/templates/instance.html")
        self.assertNotIn("'<option value=' + item", src)
        self.assertNotIn('pool + "<span', src)

    def test_create_wizard_chipset_list_does_not_concatenate_into_html(self):
        src = self._read("instances/templates/create_instance_w1.html")
        self.assertNotIn("""append('<option value="' + item""", src)

    def test_create_wizard_volume_lists_do_not_concatenate_volume_names_into_html(self):
        src = self._read("instances/templates/create_instance_w2.html")
        self.assertNotIn("'<option value=' + item", src)


# Every template line that builds HTML from JavaScript must be listed here with
# a reason; a new one fails the test and has to be reviewed (use .text() /
# .val() / DOM APIs for server data instead).
HTML_SINK = re.compile(r"""\.html\(|innerHTML\s*=|append\(\s*['"]<""")
ALLOWED_HTML_SINKS = {
    ("accounts/templates/login.html", "$btn.html("): "static spinner markup",
    ("accounts/templates/accounts/otp_login.html", "$btn.html("): "static spinner markup",
    ("instances/templates/instance.html", "//sto_input.innerHTML = pool;"): "comment",
}


class TemplateHtmlSinkInventoryTestCase(TestCase):
    def test_every_html_sink_in_templates_is_reviewed(self):
        found = set()
        for path in ROOT.glob("*/templates/**/*.html"):
            rel = str(path.relative_to(ROOT))
            for line in path.read_text().splitlines():
                if HTML_SINK.search(line):
                    found.add((rel, line.strip()))
        templates_root = ROOT / "templates"
        for path in templates_root.glob("**/*.html"):
            rel = str(path.relative_to(ROOT))
            for line in path.read_text().splitlines():
                if HTML_SINK.search(line):
                    found.add((rel, line.strip()))
        self.assertEqual(sorted(found - set(ALLOWED_HTML_SINKS)), [], "unreviewed HTML sinks")
        self.assertEqual(sorted(set(ALLOWED_HTML_SINKS) - found), [], "stale allowlist entries")
