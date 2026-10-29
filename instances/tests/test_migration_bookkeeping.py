"""What migrate_instance does around the migration itself: it records a
finished migration even when autostart fails."""

from unittest.mock import MagicMock, patch

from accounts.models import UserInstance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import TestCase
from logs.models import Logs

from instances.models import Instance
from instances.utils import migrate_instance
from vrtManager import util


class MigrationBookkeepingTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("mb-admin", "mb@example.com", "pw")
        self.source = Compute.objects.create(name="mb-src", hostname="198.51.100.8", login="root", password="", type=2)
        self.dest = Compute.objects.create(name="mb-dst", hostname="198.51.100.9", login="root", password="", type=2)
        self.vm = Instance.objects.create(compute=self.source, name="vm", uuid="u-mb", is_template=True)

    def migrate(self, vm=None, up=True, autostart=False, autostart_error=None):
        proxy = MagicMock()
        proxy.get_autostart.return_value = autostart
        with patch.object(Compute, "status", up), \
             patch("instances.utils.wvmInstances") as instances, \
             patch("instances.utils.wvmInstance") as instance, \
             patch.object(Instance, "proxy", proxy):
            instances.return_value.moveto.return_value = ("live", [])
            if autostart_error:
                instance.return_value.set_autostart.side_effect = autostart_error
            self.moveto = instances.return_value.moveto
            self.set_autostart = instance.return_value.set_autostart
            return migrate_instance(self.dest, vm or self.vm, self.admin, live=True)

    def test_autostart_is_read_from_libvirt_and_restored_on_the_destination(self):
        self.vm.__dict__["autostart"] = False  # an earlier, cached read
        self.migrate(autostart=True)
        self.set_autostart.assert_called_once_with(1)

    def test_a_failed_autostart_does_not_stop_the_records(self):
        self.migrate(autostart=True, autostart_error=util.OperationError("no autostart"))
        self.assertEqual(Instance.objects.get(id=self.vm.id).compute, self.dest)
        self.assertEqual(list(Logs.objects.order_by("id").values_list("message", "success")), [
            ("VM vm: migrate (live) to 198.51.100.9", True),
            ("VM vm: restore autostart on 198.51.100.9: no autostart", False),
        ])

    def test_a_failed_record_is_logged_as_such(self):
        with patch.object(Instance, "save", side_effect=DatabaseError("locked")), \
             self.assertRaises(DatabaseError):
            self.migrate()
        self.assertEqual(list(Logs.objects.order_by("id").values_list("message", "success")), [
            ("VM vm: migrate (live) to 198.51.100.9", True),
            ("VM vm: record the move to 198.51.100.9: DatabaseError", False),
        ])

    def test_a_record_the_destination_already_has_keeps_template_and_owners(self):
        owner = get_user_model().objects.create_user("mb-owner")
        UserInstance.objects.create(user=owner, instance=self.vm, is_change=True)
        found = Instance.objects.create(compute=self.dest, name="vm", uuid="u-mb")  # listed there meanwhile
        old_id = self.vm.id
        self.migrate()
        self.assertFalse(Instance.objects.filter(id=old_id).exists())
        found.refresh_from_db()
        self.assertTrue(found.is_template)
        self.assertEqual(UserInstance.objects.get(user=owner).instance_id, found.id)
