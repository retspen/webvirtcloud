"""The Access tab: the console of a running or paused VM, a remote viewer
only where it can reach the console, and root's password and keys when the
VM can take them."""

from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from lxml import html

UUID = "abcdabcd-0000-0000-0000-000000000000"


def tab(status=1, vdi_reachable=True, guest_access_ready=True, publickeys=("laptop",)):
    instance = SimpleNamespace(id=1, uuid=UUID, status=status, console_type="vnc")
    page = render_to_string("instances/access_tab.html", {
        "instance": instance, "compute": SimpleNamespace(id=1), "can_open_console": True, "can_change": True,
        "app_settings": SimpleNamespace(SHOW_ACCESS_ROOT_PASSWORD="True", SHOW_ACCESS_SSH_KEYS="True"),
        "publickeys": [SimpleNamespace(id=n, keyname=name) for n, name in enumerate(publickeys, 1)],
        "vdi_reachable": vdi_reachable, "guest_access_ready": guest_access_ready,
    })
    return html.fromstring(page)


class AccessTabTests(SimpleTestCase):
    def test_a_running_or_paused_vm_opens_its_console(self):
        for status, console in ((1, True), (3, True), (5, False)):
            with self.subTest(status=status):
                self.assertEqual(bool(tab(status=status).xpath("//button[@id='console_button']")), console)

    def test_a_remote_viewer_is_offered_only_where_it_reaches_the_console(self):
        for reachable in (True, False):
            with self.subTest(reachable=reachable):
                doc = tab(vdi_reachable=reachable)
                self.assertEqual(bool(doc.xpath("//a[@id='vdi_url'] | //input[@id='vdi_url_input']")), reachable)
                self.assertEqual(bool(doc.xpath("//a[contains(@href, 'getvvfile')]")), reachable)

    def test_root_s_password_is_hidden_and_waits_for_a_vm_that_can_take_it(self):
        for ready in (True, False):
            with self.subTest(ready=ready):
                doc = tab(guest_access_ready=ready)
                (field,) = doc.xpath("//input[@name='passwd']")
                self.assertEqual((field.get("type"), field.get("autocomplete")), ("password", "new-password"))
                self.assertEqual(field.xpath("ancestor::fieldset")[0].get("disabled") is not None, not ready)

    def test_without_a_saved_key_the_tab_points_to_the_profile(self):
        doc = tab(publickeys=())
        self.assertIsNotNone(doc.xpath("//select[@name='sshkeyid']/ancestor::fieldset")[0].get("disabled"))
        self.assertEqual(doc.xpath("//select[@name='sshkeyid']/option"), [])
        self.assertEqual(doc.xpath("//a[text()='Add one in your profile.']/@href"), ["/accounts/profile/"])
