"""Deleting an internal snapshot calls the backend once and shows its
refusals as messages; it no longer starts, pauses or stops the VM itself. The
other snapshot actions queue jobs (test_snapshot_jobs)."""

from datetime import datetime
from unittest.mock import PropertyMock, patch

import libvirt
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from lxml import html as lxml_html
from vrtManager import util

from appsettings.models import AppSettings
from appsettings.settings import get_settings
from computes.models import Compute
from instances.jobs import _snapshot_free_space
from instances.models import Instance
from operations.models import Claim, Operation


class SnapshotViewsTestCase(TestCase):
    def setUp(self):
        compute = Compute.objects.create(name="snap-compute", hostname="127.0.0.1:1", login="root", password="", type=1)
        self.instance = Instance.objects.create(
            compute=compute, name="snap-vm", uuid="dddddddd-eeee-ffff-0000-222222222222"
        )
        admin = get_user_model().objects.create_superuser("snap_admin", "s@example.com", "pw")
        self.client.force_login(admin)

    def post(self, view, data, error=None):
        with patch("instances.models.wvmInstance") as mock_wvm:
            proxy = mock_wvm.return_value
            method = {
                "delete_snapshot": proxy.snapshot_delete,
            }[view]
            if error:
                method.side_effect = util.OperationError(error)
            self.client.cookies.pop("messages", None)  # only this request's messages
            response = self.client.post(
                reverse(f"instances:{view}", args=[self.instance.id]),
                data,
                HTTP_REFERER=reverse("instances:instance", args=[self.instance.id]),
            )
        self.assertEqual(response.status_code, 302)
        return proxy, method, [str(m) for m in get_messages(response.wsgi_request)]

    def test_the_free_space_comes_from_the_settings_page(self):
        for percent, minimum, expected in (("20", "0.5", {"free_percent": 20.0, "free_min_gib": 0.5}),
                                           ("0", "0", {"free_percent": 0.0, "free_min_gib": 0.0}),
                                           ("-1", "x", {}), ("nan", "inf", {})):  # invalid: the backend default
            with self.subTest(percent=percent, minimum=minimum):
                AppSettings.objects.filter(key="SNAPSHOT_FREE_SPACE_PERCENT").update(value=percent)
                AppSettings.objects.filter(key="SNAPSHOT_FREE_SPACE_MIN_GIB").update(value=minimum)
                get_settings()
                self.assertEqual(_snapshot_free_space(), expected)

    def delete(self, listed):
        with patch("instances.jobs.wvmInstance") as mock_wvm:
            proxy = mock_wvm.return_value
            proxy.instance.snapshotListNames.return_value = list(listed)
            self.client.cookies.pop("messages", None)
            response = self.client.post(
                reverse("instances:delete_external_snapshot", args=[self.instance.id]),
                {"name": "a", "submission_key": "key-00000001"},
                HTTP_REFERER=reverse("instances:instance", args=[self.instance.id]),
            )
        self.assertEqual(response.status_code, 302)
        return proxy, [str(m) for m in get_messages(response.wsgi_request)]

    def test_delete_queues_a_job_and_leaves_libvirt_to_the_worker(self):
        proxy, messages = self.delete(listed=["a"])
        op = Operation.objects.get()
        self.assertEqual((op.kind, op.state, op.params),
                         ("snapshot.delete", Operation.QUEUED, {"instance": self.instance.id, "name": "a"}))
        self.assertTrue(any("being deleted" in m for m in messages), messages)
        proxy.delete_external_snapshot.assert_not_called()

    def test_a_refused_delete_becomes_a_message_and_queues_nothing(self):
        _, messages = self.delete(listed=[])
        self.assertTrue(any("has no external snapshot named a" in m for m in messages), messages)
        self.assertFalse(Operation.objects.exists())

    def test_refusals_become_messages(self):
        for view in ("delete_snapshot",):
            with self.subTest(view):
                _, _, messages = self.post(view, {"name": "a"}, error="refused for a reason")
                self.assertTrue(any("refused for a reason" in m for m in messages), messages)


class SnapshotTabTestCase(TestCase):
    setUp = SnapshotViewsTestCase.setUp  # same VM and superuser, without rerunning the view tests

    def page(self, external=(), internal=(), jobs=(), status=1, nvram=None, agent=False):
        with patch("instances.models.wvmInstance") as mock_wvm, patch.object(
            Compute, "status", new_callable=PropertyMock, return_value=True
        ):
            proxy = mock_wvm.return_value
            for getter in ("get_networks", "get_ifaces", "get_storages", "get_disk_devices",
                           "get_media_devices", "get_net_devices"):
                getattr(proxy, getter).return_value = []
            proxy.get_hostdevs.return_value = ([], [])
            proxy.get_snapshot.side_effect = lambda flag: {
                libvirt.VIR_DOMAIN_SNAPSHOT_LIST_INTERNAL: list(internal),
                libvirt.VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL: list(external),
            }[flag]
            if isinstance(jobs, Exception):
                proxy.get_snapshot_jobs.side_effect = jobs
            else:
                proxy.get_snapshot_jobs.return_value = list(jobs)
            proxy.get_status.return_value = status
            proxy.get_nvram.return_value = nvram
            proxy.is_agent_ready.return_value = agent
            proxy.get_memory.return_value = proxy.get_cur_memory.return_value = 1024
            proxy.get_max_memory.return_value = 4096
            proxy.get_vcpu.return_value = proxy.get_cur_vcpu.return_value = 1
            proxy.get_max_cpus.return_value = [1]
            proxy.get_vcpus.return_value = {}
            proxy.get_console_type.return_value = "vnc"
            response = self.client.get(reverse("instances:instance", args=[self.instance.id]))
        self.assertEqual(response.status_code, 200)
        self.proxy = proxy
        return lxml_html.fromstring(response.content)

    def snap(self, name, **kw):
        return {"name": name, "date": datetime(2026, 1, 1), "description": "", "memory": False,
                "current": False, "detaches": [], **kw}

    def test_revert_confirm_names_detached_disks_and_nvram(self):
        doc = self.page(external=[self.snap("e", detaches=[{"dev": "vdb", "path": "/pool/later.qcow2"}])],
                        nvram="/var/lib/libvirt/qemu/nvram/x_VARS.fd")
        [button] = doc.xpath("//button[@name='revert_external_snapshot']")
        text = button.get("data-confirm")
        self.assertIn("vdb (/pool/later.qcow2)", text)
        self.assertIn("NVRAM", text)

    def test_each_kind_is_listed_once_per_page(self):
        doc = self.page(internal=[self.snap("i")], external=[self.snap("e")])
        flags = sorted(c.args[0] for c in self.proxy.get_snapshot.call_args_list)
        self.assertEqual(
            flags, sorted([libvirt.VIR_DOMAIN_SNAPSHOT_LIST_INTERNAL, libvirt.VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL])
        )
        self.assertEqual(doc.xpath("//i[contains(@title, 'snapshot(s)')]/@title"), ["There are 2 snapshot(s)"])

    def test_a_failed_job_query_still_renders_the_tab(self):
        # the actions themselves check for jobs again and refuse if that fails
        doc = self.page(external=[self.snap("e")], jobs=libvirt.libvirtError("no job info"))
        self.assertEqual(len(doc.xpath("//button[@name='revert_external_snapshot']")), 1)

    def test_revert_confirm_says_a_disk_only_revert_restarts_the_guest(self):
        for status, memory, restarts in ((1, False, True), (3, False, True), (5, False, False), (1, True, False)):
            with self.subTest(status=status, memory=memory):
                doc = self.page(external=[self.snap("e", memory=memory)], status=status)
                [button] = doc.xpath("//button[@name='revert_external_snapshot']")
                self.assertEqual("powered off" in button.get("data-confirm"), restarts)

    def test_quiesce_is_checked_and_offered_with_a_running_vm_and_its_agent(self):
        for status, agent, offered in ((1, True, True), (1, False, False), (3, True, False), (5, True, False)):
            with self.subTest(status=status, agent=agent):
                [box] = self.page(status=status, agent=agent).xpath("//input[@name='quiesce']")
                self.assertIsNotNone(box.get("checked"))
                self.assertEqual(box.get("disabled") is None, offered)

    def test_memory_checkbox_only_for_a_running_vm(self):
        self.assertFalse(self.page(status=1).xpath("//input[@name='memory']")[0].get("disabled"))
        self.assertIsNotNone(self.page(status=5).xpath("//input[@name='memory']")[0].get("disabled"))

    def test_a_running_job_disables_actions(self):
        # its progress shows in the job panel, not in the tab; the tab says why the actions are off
        line = "A disk job is running on this VM; snapshot actions are unavailable until it ends."
        doc = self.page(external=[self.snap("e")], jobs=[{"dev": "vda", "cur": 1, "end": 4}])
        self.assertIn(line, doc.text_content())
        self.assertNotIn("vda 25%", doc.text_content())
        self.assertNotIn(line, self.page(external=[self.snap("e")]).text_content())
        self.assertTrue(all(b.get("disabled") is not None
                            for b in doc.xpath("//div[@id='snapshots']//button[@type='submit']")))

    def hold(self, state):
        key = f"instance:{self.instance.uuid}"
        op = Operation.objects.create(kind="snapshot.delete", username="snap_admin", submission_key="k" * 12,
                                      resource=key, resource_label="snap-vm", state=state)
        return Claim.objects.create(operation=op, resource=key, mode=Claim.EXCLUSIVE)

    def test_an_active_job_disables_actions_before_libvirt_has_a_block_job(self):
        # the button each case leaves enabled, so only the job can disable it
        cases = (("none", {}, ("takesnapshot", "takeextsnapshot")),
                 ("internal only", {"internal": [self.snap("i")]}, ("takesnapshot", "managesnapshot")),
                 ("external only", {"external": [self.snap("e")]}, ("takeextsnapshot", "managesnapshot")))
        buttons = "//div[@id='snapshots']//button[@type='submit']"

        def enabled(doc, panes):
            return [bool(doc.xpath(f"//div[@id='{pane}']//button[@type='submit' and not(@disabled)]"))
                    for pane in panes]

        for name, lists, panes in cases:
            with self.subTest(name):
                doc = self.page(**lists, status=5)
                self.assertTrue(all(enabled(doc, panes)), "enabled without a job")
                claim = self.hold(Operation.QUEUED)
                doc = self.page(**lists, status=5)
                self.assertFalse(doc.xpath(buttons + "[not(@disabled)]"), "disabled while the job holds the VM")
                self.assertNotIn("A disk job is running", doc.text_content())
                claim.operation.delete()
                self.assertTrue(all(enabled(self.page(**lists, status=5), panes)), "enabled after the job ends")

    def test_an_uncertain_job_keeps_the_buttons_disabled(self):
        self.hold(Operation.UNCERTAIN)
        doc = self.page(internal=[self.snap("i")], status=5)
        self.assertTrue(doc.xpath("//button[@name='revert_snapshot']"))
        self.assertFalse(doc.xpath("//div[@id='snapshots']//button[@type='submit'][not(@disabled)]"))

    def test_lists_are_separate(self):
        doc = self.page(internal=[self.snap("i")], external=[self.snap("e")])
        self.assertEqual(doc.xpath("//table[@id='internal-snapshots']//strong/text()"), ["i"])
        self.assertEqual(doc.xpath("//table[@id='external-snapshots']//strong/text()"), ["e"])
