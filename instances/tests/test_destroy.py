import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from instances.jobs import DeleteInstance
from instances.models import Instance
from instances import utils
from instances.utils import paths_used_on_other_computes
from libvirt import VIR_DOMAIN_UNDEFINE_KEEP_NVRAM, VIR_DOMAIN_UNDEFINE_NVRAM, VIR_ERR_NO_STORAGE_VOL, libvirtError
from logs.models import Logs
from operations.jobs import Context
from operations.models import Claim, Operation, acquire
from operations.utils import public_error_text, words
from vrtManager.util import ConnectionFailed, OperationError

UUID = "11111111-2222-3333-4444-555555555555"


class DestroyOrderTestCase(TransactionTestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("destroy_admin", "d@example.com", "pw")
        self.client.force_login(self.admin)
        self.client.raise_request_exception = False
        compute = Compute.objects.create(name="destroy-compute", hostname="127.0.0.1", login="", password="", type=4)
        self.instance = Instance.objects.create(compute=compute, name="destroy-vm", uuid=UUID)
        self.proxy = MagicMock()
        self.proxy.instance.isActive.return_value = False
        self.proxy.backing_path.return_value = None
        self.proxy.split_disk_paths_by_use.return_value = (["/pool/own.qcow2"], ["/pool/shared.qcow2"])
        # the job's VM and its compute's connection are the same host here
        for target in ("instances.jobs.wvmInstance", "instances.jobs.wvmConnect", "instances.models.wvmInstance"):
            patch(target, return_value=self.proxy).start()
        self.addCleanup(patch.stopall)

    def queue(self, **data):
        self.client.post(reverse("instances:destroy", args=[self.instance.id]),
                         {"submission_key": "key-destroy01", **data})
        return Operation.objects.get()

    def run_job(self, op):
        """The job as the worker runs it; its result."""
        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        ctx = Context(op, SimpleNamespace(identity="wvc-test:1:a"))
        DeleteInstance().precheck(op, ctx)
        return DeleteInstance().run(op, ctx)

    def test_the_page_queues_the_delete_and_changes_nothing(self):
        response = self.client.post(reverse("instances:destroy", args=[self.instance.id]),
                                    {"submission_key": "key-destroy01", "delete_disk": "true"})
        self.assertRedirects(response, reverse("instances:instance", args=[self.instance.id]),
                             fetch_redirect_response=False)
        op = Operation.objects.get()
        self.assertEqual((op.kind, op.params), ("instance.delete", {
            "instance": self.instance.pk, "delete_disk": True, "delete_nvram": False}))
        # the whole compute: a file to delete must not be attached meanwhile
        self.assertEqual(set(Claim.objects.values_list("resource", "mode")), {
            (f"compute:{self.instance.compute_id}", "exclusive"), (f"instance:{UUID}", "exclusive")})
        self.assertEqual(self.proxy.mock_calls, [])

    def test_the_nvram_goes_only_when_asked(self):
        for data, wanted, unwanted in (
            ({"delete_nvram": "1"}, VIR_DOMAIN_UNDEFINE_NVRAM, VIR_DOMAIN_UNDEFINE_KEEP_NVRAM),
            ({}, VIR_DOMAIN_UNDEFINE_KEEP_NVRAM, VIR_DOMAIN_UNDEFINE_NVRAM),
        ):
            with self.subTest(data=data):
                self.instance = Instance.objects.get_or_create(compute=self.instance.compute, name="destroy-vm",
                                                               uuid=UUID)[0]
                Operation.objects.all().delete()
                self.run_job(self.queue(**data))
                flags = self.proxy.delete.call_args[0][0]
                self.assertTrue(flags & wanted)
                self.assertFalse(flags & unwanted)

    def test_the_files_are_checked_before_the_vm_is_stopped_and_deleted_after_the_undefine(self):
        self.proxy.instance.isActive.return_value = True
        op = self.queue(delete_disk="true")
        result = self.run_job(op)
        calls = [name for name, *_ in self.proxy.mock_calls
                 if name in ("split_disk_paths_by_use", "force_shutdown", "delete", "get_volume_by_path")]
        self.assertEqual(calls, ["split_disk_paths_by_use", "force_shutdown", "delete", "get_volume_by_path"])
        self.proxy.get_volume_by_path.assert_called_once_with("/pool/own.qcow2")
        self.assertFalse(Instance.objects.filter(pk=self.instance.pk).exists())
        self.assertEqual(Operation.objects.get().intent["to_delete"], ["/pool/own.qcow2"])  # recorded first
        self.assertEqual(result["open"], reverse("instances:index"))
        self.assertEqual(words(result["warning"]), "Disk /pool/shared.qcow2 is used by another VM and was kept")
        self.assertEqual(list(Logs.objects.exclude(message="Login").values_list("message", "success")),
                         [("VM destroy-vm: delete volume /pool/own.qcow2", True)])

    def test_a_failed_undefine_deletes_no_disk(self):
        self.proxy.delete.side_effect = libvirtError("refused")
        with self.assertRaises(libvirtError):
            self.run_job(self.queue(delete_disk="true"))
        self.proxy.get_volume_by_path.assert_not_called()
        self.assertTrue(Instance.objects.filter(pk=self.instance.pk).exists())

    def test_a_disk_file_that_stays_keeps_the_files_it_needs(self):
        # the overlay is not deleted: the file below it would leave it broken
        volumes = {}

        def volume(path):
            vol = volumes.setdefault(path, MagicMock())
            if path == "/pool/vm.snap1":
                vol.delete.side_effect = libvirtError("Permission denied")
            return vol

        self.proxy.split_disk_paths_by_use.return_value = (
            ["/pool/vm.snap1", "/pool/vm.qcow2", "/pool/vm-data.qcow2"], [])
        self.proxy.get_volume_by_path.side_effect = volume
        self.proxy.backing_path.side_effect = {"/pool/vm.snap1": "/pool/vm.qcow2"}.get
        result = self.run_job(self.queue(delete_disk="true"))
        self.assertNotIn("/pool/vm.qcow2", volumes)
        volumes["/pool/vm-data.qcow2"].delete.assert_called_once_with(0)
        # each disk has its own row, and the job's end the VM's (log_entry)
        self.assertEqual(list(Logs.objects.exclude(message="Login").values_list("message", "success", "instance_uuid")), [
            ("VM destroy-vm: delete volume /pool/vm.snap1: Permission denied", False, UUID),
            ("VM destroy-vm: delete volume /pool/vm-data.qcow2", True, UUID)])
        self.assertEqual(DeleteInstance().log_entry(Operation.objects.get(), Operation.SUCCEEDED),
                         ("destroy-compute", "destroy-vm", UUID, "VM destroy-vm: delete"))
        self.assertEqual(words(result["warning"]),
                         "The VM is removed, but disk /pool/vm.snap1 was not deleted: Permission denied. "
                         "Disk /pool/vm.qcow2 was kept: a disk file that stays needs it")

    def test_when_the_files_a_kept_one_needs_are_unknown_none_of_the_rest_goes(self):
        self.proxy.split_disk_paths_by_use.return_value = (["/pool/a.qcow2", "/pool/b.qcow2"], [])
        self.proxy.get_volume_by_path.return_value.delete.side_effect = libvirtError("Permission denied")
        self.proxy.backing_path.side_effect = libvirtError("pool unreachable")
        self.run_job(self.queue(delete_disk="true"))
        self.proxy.get_volume_by_path.assert_called_once_with("/pool/a.qcow2")

    def test_a_host_that_cannot_be_checked_stops_nothing(self):
        Compute.objects.create(name="other-host", hostname="192.0.2.50", login="u", password="p", type=1)

        def connect(host, *args):
            if host == "192.0.2.50":
                raise libvirtError("unreachable")
            return MagicMock()

        self.proxy.instance.isActive.return_value = True
        self.proxy.split_disk_paths_by_use.side_effect = lambda elsewhere: elsewhere(["/pool/own.qcow2"])
        op = self.queue(delete_disk="true")
        with patch("instances.utils.wvmConnect", side_effect=connect), \
                self.assertRaisesMessage(ConnectionFailed, "The disk files cannot be checked on other-host"):
            self.run_job(op)
        self.proxy.force_shutdown.assert_not_called()
        self.proxy.delete.assert_not_called()
        self.assertFalse(Operation.objects.get().effects_started)  # the job fails without recovery
        self.assertTrue(Instance.objects.filter(pk=self.instance.pk).exists())

    def test_recovery_finishes_a_delete_libvirt_has_done(self):
        op = self.queue(delete_disk="true")
        Operation.objects.filter(pk=op.pk).update(intent={**op.intent, "to_delete": ["/pool/gone.qcow2", "/pool/own.qcow2"],
                                                          "shared": []})
        op.refresh_from_db()
        gone = libvirtError("no volume")
        gone.err = (VIR_ERR_NO_STORAGE_VOL, 0, "no volume")
        self.proxy.get_volume_by_path.side_effect = lambda path: (_ for _ in ()).throw(gone) \
            if path == "/pool/gone.qcow2" else MagicMock()
        with patch("instances.jobs._domain", return_value=None):
            outcome = DeleteInstance().reconcile(op)
        self.assertEqual((outcome.state, outcome.result), (Operation.SUCCEEDED, {"open": reverse("instances:index")}))
        self.assertFalse(Instance.objects.filter(pk=self.instance.pk).exists())
        self.assertEqual(list(Logs.objects.exclude(message="Login").values_list("message", flat=True)),
                         ["VM destroy-vm: delete volume /pool/own.qcow2"])

    def test_recovery_of_a_vm_still_on_its_host_fails(self):
        op = self.queue(delete_disk="true")
        with patch("instances.jobs._domain", return_value=MagicMock()):
            self.assertEqual(DeleteInstance().reconcile(op).state, Operation.FAILED)
        self.assertTrue(Instance.objects.filter(pk=self.instance.pk).exists())
        self.proxy.get_volume_by_path.assert_not_called()

    def test_the_api_queues_the_delete_with_its_options_as_booleans(self):
        url = f"/api/v1/computes/{self.instance.compute_id}/instances/{self.instance.id}/"
        for n, (body, content_type, deleted) in enumerate((
            ({"delete_disk": True, "submission_key": "key-api00001"}, "application/json", True),
            ("delete_disk=false&submission_key=key-api00002", "application/x-www-form-urlencoded", False),
        )):
            with self.subTest(body=body):
                Operation.objects.all().delete()
                response = self.client.delete(url, body, content_type=content_type)
                self.assertEqual(response.status_code, 202)
                self.assertEqual(Operation.objects.get().params["delete_disk"], deleted)
        self.assertEqual(self.client.delete(url, {"delete_disk": True}, content_type="application/json").status_code,
                         400)  # no submission key

    def test_destroy_and_delete_vol_hold_the_compute_exclusively(self):
        calls = []

        @contextmanager
        def record(compute, *, shared=False):
            calls.append(shared)
            yield

        with patch("instances.views.libvirt_compute_lock", record):
            self.client.post(reverse("instances:delete_vol", args=[self.instance.id]), {"dev": "vda"})
        self.assertEqual(calls, [False])

    def test_a_volume_the_vms_snapshots_need_is_kept_after_the_detach(self):
        disk = {"dev": "vdb", "path": "/pool/data.qcow2", "storage": "default", "image": "data.qcow2"}
        with patch("instances.models.wvmInstance") as wvm, patch("instances.views.wvmStorage") as storage:
            proxy = wvm.return_value
            proxy.get_disk_devices.return_value = [disk]
            proxy.paths_used_by_other_domains.return_value = set()
            proxy.wait_disk_detached.return_value = True
            storage.return_value.del_volume.side_effect = OperationError("Volume data.qcow2 is in use")
            response = self.client.post(reverse("instances:delete_vol", args=[self.instance.id]), {"dev": "vdb"})
        self.assertEqual(response.status_code, 302)
        proxy.detach_disk.assert_called_once_with("vdb")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("data.qcow2 is in use" in m and "detached" in m for m in messages), messages)

    def test_confirmation_page_takes_no_lock(self):
        calls = []

        @contextmanager
        def record(compute, *, shared=False):
            calls.append(shared)
            yield

        with patch("instances.views.libvirt_compute_lock", record), patch("instances.models.wvmInstance"):
            response = self.client.get(reverse("instances:destroy", args=[self.instance.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [])

    def test_the_confirmation_page_says_the_tpm_state_goes(self):
        for tpm, shown in (("emulator", True), (None, False), ("custom", False)):
            with self.subTest(tpm=tpm), patch("instances.models.wvmInstance") as wvm:
                wvm.return_value.get_status.return_value = 5
                wvm.return_value.get_tpm.return_value = tpm
                response = self.client.get(reverse("instances:destroy", args=[self.instance.id]))
                self.assertEqual(b"Its TPM state is deleted" in response.content, shown)

    def test_the_confirmation_page_names_the_host_only_to_whom_the_app_shows_hosts(self):
        owner = get_user_model().objects.create_user("destroy_owner", password="pw")
        self.instance.userinstance_set.create(user=owner, is_delete=True)
        for user, shown in ((self.admin, True), (owner, False)):
            with self.subTest(user=user.username), patch("instances.models.wvmInstance"):
                self.client.force_login(user)
                response = self.client.get(reverse("instances:destroy", args=[self.instance.id]))
                self.assertEqual(response.status_code, 200)
                self.assertEqual("on destroy-compute" in response.content.decode(), shown)

    def test_the_confirmation_page_of_a_paused_vm_offers_the_form(self):
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.get_status.return_value = 3  # paused
            response = self.client.get(reverse("instances:destroy", args=[self.instance.id]))
        self.assertIn('id="delete_form"', response.content.decode())


class OtherComputesTestCase(TestCase):
    """The files of a VM another host's VM or volume uses: shared storage
    holds them at the same path on every host that mounts it."""

    def setUp(self):
        self.source = Compute.objects.create(name="source", hostname="192.0.2.60", login="u", password="p", type=1)
        Compute.objects.create(name="host-b", hostname="192.0.2.61", login="u", password="p", type=1)
        Compute.objects.create(name="host-c", hostname="192.0.2.62", login="u", password="p", type=1)

    def test_the_paths_another_host_uses(self):
        hosts = self.hosts({"192.0.2.61": {"/nfs/a.qcow2", "/nfs/unrelated.qcow2"}, "192.0.2.62": {"/nfs/b.qcow2"}})
        own = ["/nfs/a.qcow2", "/nfs/b.qcow2", "/local/c.qcow2"]
        with patch("instances.utils.wvmConnect", side_effect=lambda host, *args: hosts[host]):
            self.assertEqual(paths_used_on_other_computes(self.source, own), {"/nfs/a.qcow2", "/nfs/b.qcow2"})
        # the VM's own host is checked by split_disk_paths_by_use itself; on the
        # others too, the backing files of the VM's own volumes do not count
        hosts["192.0.2.60"].paths_in_use.assert_not_called()
        hosts["192.0.2.61"].paths_in_use.assert_called_once_with(own=own)
        hosts["192.0.2.62"].paths_in_use.assert_called_once_with(own=own)

    def test_another_record_of_the_vm_s_own_host_is_skipped(self):
        # there the VM itself uses its files: they would all be kept
        hosts = self.hosts({"192.0.2.61": {"/pool/a.qcow2"}, "192.0.2.62": set()}, same_host="192.0.2.61")
        with patch("instances.utils.wvmConnect", side_effect=lambda host, *args: hosts[host]):
            self.assertEqual(paths_used_on_other_computes(self.source, ["/pool/a.qcow2"]), set())
        hosts["192.0.2.61"].paths_in_use.assert_not_called()

    def hosts(self, used, same_host=None):
        """Connections by host name; same_host is the source host under another record."""
        hosts = {"192.0.2.60": MagicMock(**{"host_uuid.return_value": "aaaaaaaa-0000-0000-0000-000000000060"})}
        for n, (host, paths) in enumerate(used.items()):
            uuid = "aaaaaaaa-0000-0000-0000-000000000060" if host == same_host else f"bbbbbbbb-0000-0000-0000-00000000000{n}"
            hosts[host] = MagicMock(**{"host_uuid.return_value": uuid, "paths_in_use.return_value": paths})
        return hosts

    def test_a_host_that_cannot_be_read_is_an_error(self):
        hosts = self.hosts({"192.0.2.61": set(), "192.0.2.62": set()})
        hosts["192.0.2.61"].paths_in_use.side_effect = libvirtError("connection refused")
        with patch("instances.utils.wvmConnect", side_effect=lambda host, *args: hosts[host]):
            with self.assertRaises(ConnectionFailed) as caught:
                paths_used_on_other_computes(self.source, ["/nfs/a.qcow2"])
        self.assertEqual(caught.exception.args[0], "The disk files cannot be checked on host-b: connection refused")
        # users who do not see hosts get neither the host nor libvirt's text
        self.assertEqual(public_error_text(caught.exception), "The host of this virtual machine cannot be reached right now.")

    def test_a_check_whose_thread_starts_late_is_an_error_not_an_empty_answer(self):
        from types import SimpleNamespace

        late = []

        class LateThread(threading.Thread):  # scheduled only after the caller gave up
            def run(self):
                late.append(self)
                time.sleep(0.3)
                super().run()
        hosts = self.hosts({"192.0.2.61": {"/nfs/a.qcow2"}})
        with patch("instances.utils.wvmConnect", side_effect=lambda host, *args: hosts[host]), \
                patch("instances.utils.USED_CHECK_WAIT", 0.1), \
                patch.object(utils, "threading", SimpleNamespace(Thread=LateThread)):
            with self.assertRaises(ConnectionFailed):
                paths_used_on_other_computes(self.source, ["/nfs/a.qcow2"])
            late[0].join(5)  # its calls end within this test

    def test_a_host_that_does_not_answer_is_an_error_in_bounded_time(self):
        # connected, but stuck (a hung NFS mount): the delete job must not wait for it for good
        hosts = self.hosts({"192.0.2.61": set(), "192.0.2.62": set()})
        stuck = threading.Event()
        self.addCleanup(stuck.set)
        hosts["192.0.2.62"].paths_in_use.side_effect = lambda own: stuck.wait(10) and set()
        with patch("instances.utils.wvmConnect", side_effect=lambda host, *args: hosts[host]), \
                patch("instances.utils.USED_CHECK_WAIT", 0.2):
            started = time.monotonic()
            with self.assertRaises(ConnectionFailed) as caught:
                paths_used_on_other_computes(self.source, ["/nfs/a.qcow2"])
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(caught.exception.args[0], "The disk files cannot be checked on host-c: it did not answer within 0.2 seconds")
        # a retry while the host still has not answered does not ask it again
        time.sleep(0.25)  # the call, started after the caller's wait began, is 0.2 s old
        with patch("instances.utils.wvmConnect", side_effect=lambda host, *args: hosts[host]), \
                patch("instances.utils.USED_CHECK_WAIT", 0.2):
            with self.assertRaises(ConnectionFailed):
                paths_used_on_other_computes(self.source, ["/nfs/a.qcow2"])
        self.assertEqual(hosts["192.0.2.62"].paths_in_use.call_count, 1)
        stuck.set()  # it answers: it is asked again
        hosts["192.0.2.62"].paths_in_use.side_effect = None
        hosts["192.0.2.62"].paths_in_use.return_value = set()
        deadline = time.monotonic() + 2
        while utils._ASKING and time.monotonic() < deadline:
            time.sleep(0.01)
        with patch("instances.utils.wvmConnect", side_effect=lambda host, *args: hosts[host]):
            self.assertEqual(paths_used_on_other_computes(self.source, ["/nfs/a.qcow2"]), set())
