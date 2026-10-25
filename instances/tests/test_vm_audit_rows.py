"""Operations on a VM write one row each: done, or failed with the reason,
named by the VM and carrying its UUID; refused input writes nothing."""

from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from libvirt import libvirtError
from logs.models import Logs
from vrtManager.util import OperationError

UUID = "11111111-2222-3333-4444-555555555555"


class VMRowTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("vm-admin", "vm@example.com", "pw"))
        self.client.raise_request_exception = False
        compute = Compute.objects.create(name="c1", hostname="192.0.2.1", login="", password="", type=4)
        self.vm = Instance.objects.create(compute=compute, name="vm", uuid=UUID)
        Logs.objects.all().delete()  # the login's row
        patcher = patch("instances.models.wvmInstance")
        self.proxy = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.proxy.instance.isActive.return_value = False

    def post(self, view, data=None, args=None):
        return self.client.post(reverse(f"instances:{view}", args=args or [self.vm.pk]), data or {},
                                REMOTE_ADDR="192.0.2.50")

    def rows(self):
        return list(Logs.objects.order_by("id").values_list("message", "success"))

    def test_a_done_row_names_the_vm_and_carries_its_uuid(self):
        self.post("poweron")
        row = Logs.objects.get()
        self.assertEqual((row.message, row.success), ("VM vm: power on", True))
        self.assertEqual((row.user, row.host, row.instance, row.instance_uuid, row.ip),
                         ("vm-admin", "c1", "vm", UUID, "192.0.2.50"))

    def test_a_raised_failure_writes_a_failed_row(self):
        self.proxy.start.side_effect = libvirtError("Requested operation is not valid")
        self.post("poweron")
        self.assertEqual(self.rows(), [("VM vm: power on: Requested operation is not valid", False)])

    def test_a_caught_failure_writes_a_failed_row(self):
        self.proxy.snapshot_delete.side_effect = libvirtError("snapshot not found")
        self.post("delete_snapshot", {"name": "snap1"})
        self.proxy.snapshot_delete.side_effect = None
        self.post("delete_snapshot", {"name": "snap1"})
        self.assertEqual(self.rows(), [("VM vm: delete snapshot snap1: snapshot not found", False),
                                       ("VM vm: delete snapshot snap1", True)])

    def test_refused_input_writes_nothing(self):
        self.post("resizevm_cpu", {"vcpu": "x", "cur_vcpu": "1"})
        self.post("set_qos", {"qos_direction": "sideways", "net-mac-0": "52:54:00:00:00:01"})
        Instance.objects.filter(pk=self.vm.pk).update(is_template=True)
        self.post("poweron")
        self.assertEqual(self.rows(), [])

    def test_qos_is_logged(self):
        self.post("set_qos", {"qos_direction": "inbound", "net-mac-0": "52:54:00:00:00:01", "qos_average": "100"})
        self.post("unset_qos", {"qos_direction": "inbound", "net-mac": "52:54:00:00:00:01"})
        self.assertEqual(self.rows(), [("VM vm: set inbound QoS on interface 52:54:00:00:00:01", True),
                                       ("VM vm: remove inbound QoS from interface 52:54:00:00:00:01", True)])

    def test_a_gstfsd_error_reply_is_a_failed_row_without_the_password(self):
        self.proxy.get_status.return_value = 5
        with patch("instances.views.gstfsd_request", side_effect=OperationError("gstfsd error: timed out")):
            self.post("rootpasswd", {"passwd": "S3cret-pass"})
        with patch("instances.views.gstfsd_request", return_value={"return": "success"}):
            self.post("rootpasswd", {"passwd": "S3cret-pass"})
        self.assertEqual(self.rows(), [("VM vm: reset root password: gstfsd error: timed out", False),
                                       ("VM vm: reset root password", True)])

    def test_an_agent_error_is_a_failed_row_without_the_password(self):
        self.proxy.get_status.return_value = 1
        self.proxy.is_agent_ready.return_value = True
        self.proxy.set_user_password.side_effect = libvirtError("guest agent didn't respond to command within '10' seconds")
        self.post("rootpasswd", {"passwd": "S3cret-pass"})
        self.assertEqual(self.rows(), [
            ("VM vm: reset root password: guest agent didn't respond to command within '10' seconds", False)])
        self.assertFalse(Logs.objects.filter(message__contains="$6$").exists())

    def test_console_password_rows_never_hold_the_password(self):
        self.proxy.get_console_type.return_value = "vnc"
        self.proxy.console_listens_locally.return_value = True
        self.proxy.set_console_passwd.return_value = False  # no graphics device
        form = {"listen_on": "127.0.0.1", "keymap": "auto"}
        self.post("update_console", {**form, "password": "Vnc-pass-1"})
        self.proxy.set_console_passwd.return_value = True
        self.post("update_console", {**form, "password": "Vnc-pass-2"})
        self.assertNotIn("Vnc-pass", str(self.rows()))
        rows = [row for row in self.rows() if "password" in row[0]]
        self.assertEqual(rows, [("VM vm: set console password: The VM has no graphics device", False),
                                       ("VM vm: set console password", True)])

    def test_a_console_setting_that_changed_nothing_writes_no_row(self):
        self.proxy.get_console_type.return_value = "vnc"
        self.proxy.set_console_keymap.return_value = False  # no graphics device
        self.proxy.set_console_listener_addr.return_value = False  # a socket, no address
        self.post("update_console", {"listen_on": "0.0.0.0", "keymap": "de"})
        self.proxy.set_console_keymap.return_value = None  # the define's result
        self.proxy.set_console_listener_addr.return_value = None
        self.post("update_console", {"listen_on": "0.0.0.0", "keymap": "de"})
        self.assertEqual(self.rows(), [("VM vm: set console keymap de", True),
                                       ("VM vm: set console listen address 0.0.0.0", True)])

    def test_a_deleted_vm_and_each_of_its_disks_have_their_own_row(self):
        self.proxy.split_disk_paths_by_use.return_value = (["/pool/a.qcow2", "/pool/b.qcow2"], [])
        volume = self.proxy.get_volume_by_path.return_value
        volume.delete.side_effect = [libvirtError("Permission denied"), None]
        self.client.post(reverse("instances:destroy", args=[self.vm.pk]), {"delete_disk": "1"})
        self.assertFalse(Instance.objects.filter(pk=self.vm.pk).exists())
        self.assertEqual(self.rows(), [("VM vm: delete", True),
                                       ("VM vm: delete volume /pool/a.qcow2: Permission denied", False),
                                       ("VM vm: delete volume /pool/b.qcow2", True)])
        self.assertEqual(set(Logs.objects.values_list("instance_uuid", flat=True)), {UUID})

    def test_a_disk_delete_logs_the_detach_and_the_volume(self):
        disk = {"dev": "vdb", "path": "/pool/data.qcow2", "storage": "default", "image": "data.qcow2"}
        self.proxy.get_disk_devices.return_value = [disk]
        self.proxy.paths_used_by_other_domains.return_value = set()
        with patch("instances.views.wvmStorage"):
            self.proxy.wait_disk_detached.return_value = False
            self.post("delete_vol", {"dev": "vdb"})
            self.proxy.wait_disk_detached.return_value = True
            self.post("delete_vol", {"dev": "vdb"})
        self.assertEqual(self.rows(), [
            ("VM vm: detach disk vdb", True),
            ("VM vm: delete volume default/data.qcow2: the guest has not released the disk", False),
            ("VM vm: detach disk vdb", True),
            ("VM vm: delete volume default/data.qcow2", True),
        ])


class DefineFromXmlRowTests(TestCase):
    def post(self, xml):
        conn = libvirt.open("test:///default")
        self.addCleanup(conn.close)
        compute = Compute.objects.create(name="testdrv", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("xml", "xml@example.com", "pw"))
        Logs.objects.all().delete()
        with patch("vrtManager.connection.connection_manager.get_connection", return_value=conn):
            self.client.post(reverse("instances:create_instance_select_type", args=[compute.id]),
                             {"create_xml": "", "dom_xml": xml})
        return Logs.objects.get()

    def test_a_defined_vm_has_its_uuid(self):
        row = self.post("<domain type='test'><name>from-xml</name><memory>1024</memory>"
                        "<os><type>hvm</type></os></domain>")
        self.assertEqual((row.message, row.success), ("VM from-xml: define from XML", True))
        self.assertEqual(row.instance_uuid, Instance.objects.get(name="from-xml").uuid)

    def test_a_refused_definition_is_a_failed_row(self):
        row = self.post("<domain type='nope'><name>new</name><memory>1024</memory></domain>")
        self.assertFalse(row.success)
        self.assertTrue(row.message.startswith("VM new: define from XML: "))


class JobRowTests(TestCase):
    def test_vm_jobs_carry_the_uuid_of_their_vm(self):
        from operations.jobs import get_kind
        from operations.models import Operation

        new = {"compute": 1, "uuid": UUID, "name": "web-2"}
        cases = [
            ("instance.create", "c1/web-2", {}, new, ("c1", "web-2", UUID, "VM web-2: create")),
            ("instance.clone", "c1/web-1", {}, new, ("c1", "web-2", UUID, "VM web-2: clone from web-1")),
            ("snapshot.delete", "c1/web-1", {"name": "s1"}, {"uuid": UUID},
             ("c1", "web-1", UUID, "VM web-1: delete external snapshot s1 (failed)")),
        ]
        for kind, label, params, intent, entry in cases:
            with self.subTest(kind=kind):
                op = Operation(kind=kind, resource_label=label, params=params, intent=intent)
                state = Operation.FAILED if kind == "snapshot.delete" else Operation.SUCCEEDED
                self.assertEqual(get_kind(kind).log_entry(op, state), entry)


class MigrationResolutionRowTests(TestCase):
    def test_a_resolved_migration_carries_the_vm_uuid(self):
        from operations import jobs
        from operations.models import Operation

        admin = get_user_model().objects.create_superuser("res-admin", "res@example.com", "pw")
        op = Operation.objects.create(kind="instance.migrate", user=admin, username=admin.username,
                                      submission_key="key-res-00000001", resource="instance:" + UUID,
                                      resource_label="c1/vm", state=Operation.UNCERTAIN,
                                      intent={"compute": 1, "uuid": UUID})
        jobs.resolve(op.pk, admin, Operation.SUCCEEDED, "the VM runs on the target")
        row = Logs.objects.get(message__contains="resolved")
        self.assertEqual((row.instance, row.instance_uuid, row.success), ("c1/vm", UUID, True))
