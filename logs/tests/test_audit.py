from unittest import mock

import libvirt

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase

from computes.models import Compute
from logs.audit import audit, changed_fields, failed, request_ip, snapshot, write
from logs.models import Logs
from logs.views import addlogmsg
from operations import claims
from vrtManager.util import OperationError


class WriteTests(TestCase):
    def test_a_row_has_its_fields(self):
        write("bob", "host1", "", "Compute c: delete", True, "192.0.2.7")
        row = Logs.objects.get()
        self.assertEqual((row.user, row.host, row.instance), ("bob", "host1", ""))
        self.assertEqual(row.message, "Compute c: delete")
        self.assertIs(row.success, True)
        self.assertEqual(row.ip, "192.0.2.7")

    def test_long_values_are_cut(self):
        write("u" * 200, "h" * 300, "i" * 200, "m" * 5000)
        row = Logs.objects.get()
        self.assertEqual(len(row.user), 150)
        self.assertEqual(len(row.host), 255)
        self.assertEqual(len(row.instance), 120)
        self.assertEqual(len(row.message), 5000)

    def test_a_failed_write_inside_a_transaction_leaves_it_usable(self):
        with self.assertLogs("logs.audit", "WARNING") as logs:
            with transaction.atomic():
                with mock.patch.object(Logs.objects, "create", side_effect=IntegrityError):
                    write("bob", "-", "", "msg")
                get_user_model().objects.create_user("after")
        self.assertEqual(len(logs.output), 1)
        self.assertTrue(get_user_model().objects.filter(username="after").exists())

    def test_the_file_line_keeps_one_line(self):
        with self.assertLogs("logs.audit", "WARNING") as logs:
            with mock.patch.object(Logs.objects, "create", side_effect=IntegrityError):
                write("bob", "-", "", "a\nb")
        self.assertNotIn("\n", logs.records[0].getMessage())
        self.assertIn("a\\nb", logs.records[0].getMessage())

    def test_a_failing_file_logger_raises_nothing(self):
        with mock.patch.object(Logs.objects, "create", side_effect=IntegrityError), mock.patch(
            "logs.audit.logger.warning", side_effect=OSError
        ):
            self.assertIsNone(write("bob", "-", "", "msg"))

    def test_ips(self):
        rf = RequestFactory()
        self.assertEqual(request_ip(rf.get("/", REMOTE_ADDR="192.0.2.7")), "192.0.2.7")
        self.assertIsNone(request_ip(rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="not-an-ip")))
        self.assertEqual(request_ip(rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="")), "127.0.0.1")
        self.assertIsNone(request_ip(rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="fe80::1%eth0")))
        self.assertIsNone(request_ip(rf.get("/", REMOTE_ADDR="")))

    def test_addlogmsg_still_writes(self):
        addlogmsg("u", "h", "vm", "Destroy")
        row = Logs.objects.get()
        self.assertEqual((row.user, row.host, row.instance, row.message), ("u", "h", "vm", "Destroy"))
        self.assertIsNone(row.success)
        self.assertIsNone(row.ip)


class AuditTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("bob")
        self.request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.7")
        self.request.user = self.user
        self.compute = Compute(name="c", hostname="192.0.2.5", type=1)

    def row(self):
        return Logs.objects.get()

    def test_a_block_that_ends_writes_done(self):
        with audit(self.request, self.compute, "Compute c (192.0.2.5)", "delete"):
            pass
        row = self.row()
        self.assertEqual(row.message, "Compute c (192.0.2.5): delete")
        self.assertIs(row.success, True)
        self.assertEqual((row.host, row.user, row.ip), ("c", "bob", "192.0.2.7"))

    def test_a_block_that_raises_writes_failed_and_reraises(self):
        error = OperationError("in use")
        with self.assertRaises(OperationError) as caught:
            with audit(self.request, self.compute, "Compute c", "delete"):
                raise error
        self.assertIs(caught.exception, error)
        row = self.row()
        self.assertEqual(row.message, "Compute c: delete: in use")
        self.assertIs(row.success, False)

    def reason_row(self, exc):
        Logs.objects.all().delete()
        with self.assertRaises(type(exc)):
            with audit(self.request, None, "Compute c", "delete"):
                raise exc
        return self.row().message

    def test_reasons(self):
        self.assertEqual(
            self.reason_row(claims.Busy(None)),
            "Compute c: delete: A short operation is in progress on this resource; try again in a moment.",
        )
        self.assertNotIn("secret", self.reason_row(libvirt.libvirtError("password=secret")))
        self.assertEqual(self.reason_row(ValueError("<secret/>")), "Compute c: delete: ValueError")

    def test_the_block_sets_the_action_or_skips(self):
        with audit(self.request, self.compute, "Compute c", "edit") as entry:
            entry.action = "change hostname"
        self.assertEqual(self.row().message, "Compute c: change hostname")
        Logs.objects.all().delete()
        with audit(self.request, self.compute, "Compute c", "edit") as entry:
            entry.skip = True
        self.assertFalse(Logs.objects.exists())
        with self.assertRaises(ValueError):
            with audit(self.request, self.compute, "Compute c", "edit") as entry:
                entry.skip = True
                raise ValueError
        self.assertEqual(self.row().message, "Compute c: edit: ValueError")
        self.assertIs(self.row().success, False)

    def test_failed_writes_a_refusal(self):
        failed(self.request, None, "Network lab", "create", "Name in use")
        row = self.row()
        self.assertEqual(row.message, "Network lab: create: Name in use")
        self.assertEqual(row.host, "-")
        self.assertIs(row.success, False)

    def test_changed_fields(self):
        compute = Compute.objects.create(name="c", hostname="192.0.2.5", type=1, password="pw")
        before = snapshot(compute)
        self.assertEqual(changed_fields(before, snapshot(compute)), [])
        compute.hostname = "192.0.2.6"
        self.assertEqual(changed_fields(before, snapshot(compute)), ["hostname"])
        before = snapshot(self.user)
        self.user.groups.add(Group.objects.create(name="g"))
        self.assertEqual(changed_fields(before, snapshot(self.user)), ["groups"])
