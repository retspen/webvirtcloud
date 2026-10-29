"""Moving a disk to another pool of its host runs as a job: the page queues
it, the worker moves it, recovery ends a copy no worker waits for and reads
the outcome from the VM's definitions."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse
from libvirt import libvirtError

from appsettings.settings import get_settings
from computes.models import Compute
from instances.jobs import MoveDisk
from instances.models import Instance
from operations.jobs import Cancelled, Context, get_kind
from operations.models import Claim, Operation, acquire

UUID = "41414141-4242-5353-6464-757575757575"
OLD, NEW = "/var/lib/libvirt/images/vm.qcow2", "/srv/fast/vm.qcow2"


class MoveDiskJobTestCase(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.compute = Compute.objects.create(name="mv-host", hostname="192.0.2.60", login="root", password="", type=1)
        self.vm = Instance.objects.create(compute=self.compute, name="mv-vm", uuid=UUID)
        self.admin = get_user_model().objects.create_superuser("mv_admin", "a@example.com", "pw")
        self.client.force_login(self.admin)
        patch.object(Compute, "status", True).start()
        self.proxy = patch("instances.jobs.wvmInstance").start().return_value
        self.proxy.disk_move_plan.return_value = {
            "dev": "vda", "path": OLD, "dest": NEW, "running": True,
            "volume": MagicMock(**{"storagePoolLookupByVolume.return_value.name.return_value": "default"})}
        patch("instances.views.get_instance", return_value=self.vm).start()
        self.addCleanup(patch.stopall)

    def queue(self, **form):
        self.client.post(reverse("instances:move_disk", args=[self.vm.pk]),
                         {"dev": "vda", "pool": "fast", "submission_key": "key-move0001", **form})
        return Operation.objects.filter(kind="disk.move").first()

    def start(self, op):
        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        return Context(op, SimpleNamespace(identity="wvc-test:1:a"))

    def test_the_page_queues_it_and_the_worker_moves_it(self):
        op = self.queue()
        self.assertTrue({(f"instance:{UUID}", "exclusive"), (f"volume:{self.compute.pk}:default/vm.qcow2", "exclusive"),
                         (f"volume:{self.compute.pk}:fast/vm.qcow2", "exclusive")}
                        <= set(Claim.objects.values_list("resource", "mode")))
        self.proxy.move_disk.assert_not_called()  # nothing ran in the request
        ctx = self.start(op)
        get_kind(op.kind).precheck(op, ctx)
        with patch("instances.jobs.wvmConnect") as hosts:
            hosts.return_value.paths_in_use.return_value = set()
            result = get_kind(op.kind).run(op, ctx)
        self.proxy.move_disk.assert_called_once()
        self.proxy.disk_move_plan.return_value["volume"].delete.assert_called_once_with(0)  # the source went
        op.refresh_from_db()
        self.assertEqual((op.intent["path"], op.intent["dest"], result), (OLD, NEW, {"left_behind": []}))

    def test_a_source_file_any_host_may_use_is_left_behind(self):
        """Shared storage: a VM or volume of another host may use it."""
        Compute.objects.create(name="mv-other", hostname="192.0.2.61", login="root", password="", type=1)
        cases = ((set(), {OLD}, None), (set(), set(), libvirtError("unreachable")),
                 (set(), set(), "delete fails"))
        for n, (here, other, problem) in enumerate(cases):
            with self.subTest(case=n):
                Operation.objects.all().delete()
                op = self.queue(submission_key=f"key-left{n:04d}")
                ctx = self.start(op)
                volume = self.proxy.disk_move_plan.return_value["volume"]
                volume.delete.reset_mock()
                volume.delete.side_effect = libvirtError("busy") if problem == "delete fails" else None
                with patch("instances.jobs.wvmConnect") as hosts:
                    reads = [here, other] if not isinstance(problem, libvirtError) else [here, problem]
                    hosts.return_value.paths_in_use.side_effect = reads
                    result = get_kind(op.kind).run(op, ctx)
                self.assertEqual(result, {"left_behind": [OLD]})
                self.assertEqual(volume.delete.called, problem == "delete fails")

    def test_only_a_superuser_with_a_disk_name_queues_it(self):
        self.assertIsNone(self.queue(dev="vda']"))
        self.client.force_login(get_user_model().objects.create_user("mv_user", password="pw"))
        self.assertIsNone(self.queue())

    def test_a_cancel_ends_cancelled_only_when_the_vm_kept_its_file(self):
        op = self.queue()
        ctx = self.start(op)
        self.proxy.move_disk.side_effect = libvirtError("The copy of vda ended before it was complete")
        self.proxy.instance.blockJobInfo.return_value = {}
        self.proxy.disk_named.return_value = {OLD}
        Operation.objects.filter(pk=op.pk).update(cancel_requested=True)
        with self.assertRaises(Cancelled):
            get_kind(op.kind).run(op, ctx)
        # the pivot may have happened: the error stands, not a cancel
        self.proxy.disk_named.return_value = {NEW}
        with self.assertRaisesRegex(libvirtError, "ended before it was complete"):
            get_kind(op.kind).run(op, ctx)

    def reconcile(self, named, job=None, mirror=NEW):
        op = Operation(params={"instance": self.vm.pk, "dev": "vda", "pool": "fast"},
                       intent={"compute": self.compute.pk, "uuid": UUID, "path": OLD, "dest": NEW})
        dom = self.proxy.instance
        dom.isActive.return_value = True
        dom.blockJobInfo.return_value = job or {}
        dom.XMLDesc.return_value = (f"<domain><devices><disk><target dev='vda'/><mirror><source file='{mirror}'/>"
                                    "</mirror></disk></devices></domain>")
        self.proxy.disk_named.return_value = named
        return MoveDisk().reconcile(op)

    def test_recovery_reads_the_definitions(self):
        self.assertEqual(self.reconcile({NEW}).state, Operation.SUCCEEDED)
        failed = self.reconcile({OLD})
        self.assertEqual((failed.state, failed.error), (Operation.FAILED, f"The disk stayed in {OLD}; remove {NEW} "
                                                                           "if it is there"))
        self.assertEqual(self.reconcile({OLD, NEW}).state, Operation.UNCERTAIN)
        self.proxy.instance.blockJobAbort.assert_not_called()

    def test_recovery_ends_the_copy_no_worker_waits_for(self):
        self.assertEqual(self.reconcile({OLD}, job={"cur": 2, "end": 2}).state, Operation.FAILED)
        self.proxy.instance.blockJobAbort.assert_called_once_with("vda", 0)
        # a block job of something else is not ended
        self.proxy.instance.blockJobAbort.reset_mock()
        self.assertEqual(self.reconcile({OLD}, job={"cur": 1, "end": 2}, mirror="/other").state, Operation.UNCERTAIN)
        self.proxy.instance.blockJobAbort.assert_not_called()
