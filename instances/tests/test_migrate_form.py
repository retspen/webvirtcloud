"""The migrate form shows the switches the VM's state uses and ticks auto
converge for a running VM, and the API uses the same default: it only slows
a VM that the migration cannot keep up with. A VM that cannot migrate gets
the reason instead."""

from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import html
from operations.models import Operation
from rest_framework.test import APIClient

DOMAIN = """<domain type='test'><name>migrate-form-vm</name><memory unit='MiB'>128</memory><vcpu>1</vcpu>
<os><type arch='i686'>hvm</type></os></domain>"""


class MigrateFormTests(TestCase):
    def setUp(self):
        self.conn = libvirt.open("test:///default")
        self.addCleanup(self.conn.close)
        self.domain = self.conn.defineXML(DOMAIN)
        self.addCleanup(self.remove_domain)
        self.compute = Compute.objects.create(name="mf", hostname="localhost", login="", password="", type=4)
        self.other = Compute.objects.create(name="mf-other", hostname="198.51.100.30", login="", password="", type=4)
        self.vm = Instance.objects.create(compute=self.compute, name=self.domain.name(), uuid=self.domain.UUIDString())
        for target, value in (("get_machine_types", ["pc"]), ("get_nwfilters", [])):
            patcher = patch(f"vrtManager.connection.wvmConnect.{target}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.admin = get_user_model().objects.create_superuser("mf-admin", "mf@example.com", "pw")

    def remove_domain(self):
        if self.domain.isActive():
            self.domain.destroy()
        self.domain.undefine()

    def migrate_form(self):
        self.client.force_login(self.admin)
        with patch("vrtManager.connection.connection_manager.get_connection", return_value=self.conn):
            page = self.client.get(reverse("instances:instance", args=[self.vm.id])).content
        (form,) = html.fromstring(page).xpath("//form[@action=$a]", a=reverse("instances:migrate", args=[self.vm.id]))
        return form

    def test_auto_converge_is_ticked_for_a_running_vm(self):
        self.domain.create()
        self.assertEqual(self.migrate_form().xpath(".//input[@name='autoconverge']/@checked"), ["checked"])

    def test_each_state_shows_the_switches_it_uses(self):
        # the mode follows the state: no Offline switch; unsafe, auto converge and compressed apply to a running VM
        for state, switches in (("shut off", ["delete_source"]),
                                ("running", ["live_migrate", "autoconverge", "compress", "unsafe_migrate", "delete_source"]),
                                ("paused", ["live_migrate", "delete_source"])):
            with self.subTest(state):
                if state == "running":
                    self.domain.create()
                elif state == "paused":
                    self.domain.suspend()
                self.assertEqual(self.migrate_form().xpath(".//input[@type='checkbox']/@name"), switches)

    def test_a_vm_with_no_other_host_gets_the_reason(self):
        self.other.delete()
        form = self.migrate_form()
        self.assertIn("There is no other host to migrate to.", form.text_content())
        self.assertEqual(form.xpath(".//button[@name='migrate']"), [])

    def test_the_api_uses_auto_converge_unless_told_otherwise(self):
        api = APIClient()
        api.force_authenticate(self.admin)
        request = {"instance": self.vm.id, "target_compute": self.other.id, "live": True, "offline": False}
        with patch("instances.api.viewsets.jobs.submit") as submit:
            submit.return_value = Operation.objects.create(kind="instance.migrate", user=self.admin,
                                                           username=self.admin.username, submission_key="key-api00000")
            for n, encoding in enumerate(("json", "multipart"), 1):
                api.post("/api/v1/migrate/", {**request, "submission_key": f"key-api0000{n}"}, format=encoding)
            api.post("/api/v1/migrate/", {**request, "autoconverge": False, "submission_key": "key-api00003"},
                     format="json")
            api.post("/api/v1/migrate/", {**request, "unsafe": True, "submission_key": "key-api00004"}, format="json")
        self.assertEqual([c.args[2]["autoconverge"] for c in submit.call_args_list], [True, True, False, True])
        self.assertEqual([c.args[2]["unsafe"] for c in submit.call_args_list], [False, False, False, True])
