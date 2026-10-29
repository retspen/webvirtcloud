"""A migration runs as a job: the page queues it, the worker migrates."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse

from appsettings.settings import get_settings
from computes.models import Compute
from instances.jobs import MigrateInstance
from instances.models import Instance
from libvirt import libvirtError
from operations.jobs import Cancelled, Context, get_kind
from operations.models import Claim, Operation, acquire

UUID = "31313131-4242-5353-6464-757575757575"


class MigrateJobTestCase(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.source = Compute.objects.create(name="mig-src", hostname="192.0.2.50", login="root", password="", type=1)
        self.dest = Compute.objects.create(name="mig-dst", hostname="192.0.2.51", login="root", password="", type=1)
        self.vm = Instance.objects.create(compute=self.source, name="mig-vm", uuid=UUID)
        self.client.force_login(get_user_model().objects.create_superuser("mig_admin", "a@example.com", "pw"))
        proxy = MagicMock()
        proxy.get_autostart.return_value = False
        proxy.get_nvram.return_value = None
        patch.object(Compute, "status", True).start()
        patch.object(Instance, "proxy", proxy).start()
        self.dest_conn = patch("instances.utils.wvmInstances").start().return_value
        self.dest_conn.moveto.return_value = ("live", [])
        self.addCleanup(patch.stopall)

    def queue(self, **form):
        self.client.post(reverse("instances:migrate", args=[self.vm.pk]),
                         {"compute_id": self.dest.pk, "submission_key": "key-mig00001", **form})
        return Operation.objects.get()

    def start(self, op):
        """The job as the worker takes it."""
        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        return Context(op, SimpleNamespace(identity="wvc-test:1:a"))

    def test_the_worker_migrates_and_moves_the_record(self):
        op = self.queue(live_migrate="true")
        self.assertEqual(set(Claim.objects.values_list("resource", "mode")), {
            (f"instance:{UUID}", "exclusive"), (f"name:{self.dest.pk}:mig-vm", "exclusive"),
            (f"compute:{self.source.pk}", "shared"), (f"reconcile:{self.source.pk}", "exclusive"),
            (f"compute:{self.dest.pk}", "shared"), (f"reconcile:{self.dest.pk}", "exclusive")})
        self.dest_conn.moveto.assert_not_called()  # nothing ran in the request
        ctx = self.start(op)
        get_kind(op.kind).precheck(op, ctx)
        get_kind(op.kind).run(op, ctx)
        self.assertTrue(self.dest_conn.moveto.call_args.args[2])  # live
        self.vm.refresh_from_db()
        self.assertEqual(self.vm.compute, self.dest)

    def test_recovery_reads_where_the_vm_is(self):
        op = Operation(params={"instance": self.vm.pk, "target": self.dest.pk},
                       intent={"compute": self.source.pk, "uuid": UUID})
        dom = MagicMock()
        dom.isActive.return_value = False
        with patch("instances.jobs._domain", side_effect=[dom, None]):  # source, destination
            self.assertEqual(MigrateInstance().reconcile(op).state, Operation.FAILED)
        dom.isActive.return_value = True
        dom.jobInfo.return_value = [2] + [0] * 11  # VIR_DOMAIN_JOB_UNBOUNDED
        with patch("instances.jobs._domain", side_effect=[dom, dom]):
            self.assertEqual(MigrateInstance().reconcile(op).state, Operation.RUNNING)
        with patch("instances.jobs._domain", side_effect=[None, dom]):
            self.assertEqual(MigrateInstance().reconcile(op).state, Operation.SUCCEEDED)
        self.vm.refresh_from_db()
        self.assertEqual(self.vm.compute, self.dest)

    def test_a_copy_claims_its_volume_on_both_computes(self):
        Instance.proxy.get_disk_devices.return_value = [
            {"dev": "vda", "storage": "default", "image": "mig-vm.qcow2", "path": "/i/mig-vm.qcow2"},
            {"dev": "vdb", "storage": None, "image": "/dev/sdb", "path": "/dev/sdb"}]
        op = self.queue(live_migrate="true", delete_source="true", **{"pool-vda": "fast", "pool-vdb": ""})
        self.assertTrue({(f"volume:{self.source.pk}:default/mig-vm.qcow2", "exclusive"),
                         (f"volume:{self.dest.pk}:fast/mig-vm.qcow2", "exclusive")}
                        <= set(Claim.objects.values_list("resource", "mode")))
        self.assertEqual((op.params["disk_pools"], op.params["delete_source"]), ({"vda": "fast"}, True))
        ctx = self.start(op)
        get_kind(op.kind).run(op, ctx)
        self.assertEqual(self.dest_conn.moveto.call_args.kwargs["pools"], {"vda": "fast"})

    def test_the_migrate_tab_lists_each_disk_with_where_it_can_go(self):
        Instance.proxy.instance.XMLDesc.return_value = "<domain/>"
        Instance.proxy.get_status.return_value = 5
        with patch("instances.views.wvmInstances") as instances:
            dest = instances.return_value
            fast, default = MagicMock(), MagicMock()
            fast.info.return_value = default.info.return_value = [2, 0, 0, 8 << 30]
            dest.file_pools.return_value = {"fast": (fast, "/srv/fast"), "default": (default, "/i")}
            dest.disk_plan.return_value = [
                {"target": "vda", "path": "/i/mig-vm.qcow2", "capacity": 1 << 30, "shared": False, "refusal": None},
                {"target": "sda", "path": "/i/os.iso", "capacity": 1 << 20, "shared": False,
                 "refusal": "an image is not copied; eject it first"}]
            page = self.client.get(reverse("instances:migrate_plan", args=[self.vm.pk]),
                                   {"compute_id": self.dest.pk}).content.decode()
        dest.close.assert_called_once_with()
        # the pool on the disk's directory is chosen
        self.assertIn('<option value="default" selected>Copy to default (8.0\xa0GB free)</option>', page)
        self.assertIn('<option value="fast">Copy to fast (8.0\xa0GB free)</option>', page)
        self.assertIn("Cannot be copied: an image is not copied; eject it first", page)
        self.assertIn("A shut-off VM is started paused for a copy", page)
        self.assertEqual(self.client.get(reverse("instances:migrate_plan", args=[self.vm.pk])).status_code, 404)

    def test_a_cancelled_migration_ends_cancelled_and_the_vm_stays(self):
        op = self.queue(live_migrate="true")
        ctx = self.start(op)
        self.dest_conn.moveto.side_effect = libvirtError("operation aborted: migration out: canceled by client")
        Operation.objects.filter(pk=op.pk).update(cancel_requested=True)
        with self.assertRaises(Cancelled):
            get_kind(op.kind).run(op, ctx)
        self.vm.refresh_from_db()
        self.assertEqual(self.vm.compute, self.source)

    def test_cancel_and_progress_ask_the_source_vm(self):
        op = self.queue(live_migrate="true")
        with patch("instances.jobs.wvmInstance") as proxy:
            proxy.return_value.instance.jobInfo.return_value = [2, 0, 0, 1000, 250] + [0] * 7
            self.assertEqual(get_kind(op.kind).progress(op), (250, 1000))
            get_kind(op.kind).cancel(op)
        proxy.return_value.instance.abortJob.assert_called_once_with()

    def test_a_cancel_before_libvirt_starts_the_migration_waits_for_it(self):
        op = self.queue(live_migrate="true")
        self.start(op)
        with patch("instances.jobs.wvmInstance") as proxy, patch("instances.jobs.time.sleep") as sleep:
            dom = proxy.return_value.instance
            dom.isActive.return_value = True
            dom.jobInfo.side_effect = [[0] * 12, [2] + [0] * 11]  # no job yet, then the migration
            get_kind(op.kind).cancel(op)
        sleep.assert_called_once()
        dom.abortJob.assert_called_once_with()
        Operation.objects.filter(pk=op.pk).update(state=Operation.SUCCEEDED)  # ended before libvirt began
        with patch("instances.jobs.wvmInstance") as proxy:
            proxy.return_value.instance.isActive.return_value = False
            get_kind(op.kind).cancel(op)
        proxy.return_value.instance.abortJob.assert_not_called()
