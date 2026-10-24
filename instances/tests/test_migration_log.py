"""A migration is logged where it runs (migrate_instance, in the job): the
mode it used on success, the error on failure, and each later step that
failed in a row of its own."""

from unittest.mock import MagicMock, patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from libvirt import libvirtError
from logs.models import Logs

from instances.models import Instance
from instances.utils import migrate_instance
from vrtManager import util


def rows():
    return list(Logs.objects.order_by("id").values_list("message", "success"))


class MigrationLogTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("ml-admin", "ml@example.com", "pw")
        self.source = Compute.objects.create(name="ml-src", hostname="198.51.100.8", login="root", password="", type=2)
        self.dest = Compute.objects.create(name="ml-dst", hostname="198.51.100.9", login="root", password="", type=2)
        self.vm = Instance.objects.create(compute=self.source, name="vm", uuid="u-ml")

    def migrate(self, outcome, nvram=None, remove_nvram=True, **request):
        self.proxy = MagicMock()
        self.proxy.get_autostart.return_value = False
        self.proxy.get_nvram.return_value = nvram
        if isinstance(remove_nvram, Exception):
            self.proxy.remove_nvram.side_effect = remove_nvram
        else:
            self.proxy.remove_nvram.return_value = remove_nvram
        with patch.object(Compute, "status", True), \
             patch("instances.utils.wvmInstances") as instances, \
             patch("instances.utils.wvmInstance"), \
             patch.object(Instance, "proxy", self.proxy), \
             patch.object(Instance, "autostart", False):
            if isinstance(outcome, Exception):
                instances.return_value.moveto.side_effect = outcome
            else:
                instances.return_value.moveto.return_value = outcome
            return migrate_instance(self.dest, self.vm, self.admin, **request)

    def test_the_nvram_file_left_on_the_source_is_removed(self):
        self.migrate("live", nvram="/var/lib/libvirt/qemu/nvram/vm_VARS.fd", live=True)
        path, destination = self.proxy.remove_nvram.call_args[0]
        self.assertEqual(path, "/var/lib/libvirt/qemu/nvram/vm_VARS.fd")
        self.assertIsNotNone(destination)
        self.assertEqual(rows(), [("VM vm: migrate (live) to 198.51.100.9", True)])

    def test_a_vm_without_nvram_removes_nothing(self):
        self.migrate("live", live=True)
        self.assertFalse(self.proxy.remove_nvram.called)

    def test_a_failed_nvram_removal_is_logged_but_the_migration_stands(self):
        self.migrate("live", nvram="/var/lib/libvirt/qemu/nvram/vm_VARS.fd",
                     remove_nvram=libvirtError("cannot delete"), live=True)
        self.assertEqual(rows(), [
            ("VM vm: migrate (live) to 198.51.100.9", True),
            ("VM vm: remove NVRAM file /var/lib/libvirt/qemu/nvram/vm_VARS.fd on the source: cannot delete", False),
        ])
        self.vm.refresh_from_db()
        self.assertEqual(self.vm.compute, self.dest)

    def test_any_nvram_removal_error_still_records_the_migration(self):
        self.migrate("live", nvram="/var/lib/libvirt/qemu/nvram/vm_VARS.fd",
                     remove_nvram=AttributeError("unexpected"), live=True)
        self.vm.refresh_from_db()
        self.assertEqual(self.vm.compute, self.dest)
        # an unknown error gives only its class name
        self.assertEqual(rows()[-1], ("VM vm: remove NVRAM file /var/lib/libvirt/qemu/nvram/vm_VARS.fd on the source: "
                                      "AttributeError", False))

    def test_a_failed_migration_removes_nothing(self):
        with self.assertRaises(util.OperationError):
            self.migrate(util.OperationError("no"), nvram="/var/lib/libvirt/qemu/nvram/vm_VARS.fd", live=True)
        self.assertFalse(self.proxy.remove_nvram.called)

    def test_success_names_the_mode_used(self):
        self.migrate("non-live, compressed", live=False, compress=True)
        log = Logs.objects.get()
        self.assertEqual(log.message, "VM vm: migrate (non-live, compressed) to 198.51.100.9")
        self.assertEqual((log.user, log.host, log.instance, log.instance_uuid), ("ml-admin", "ml-src", "vm", "u-ml"))

    def test_success_names_the_migration_address(self):
        self.dest.migration_address = "203.0.113.9"
        self.migrate("live", live=True)
        self.assertEqual(Logs.objects.get().message, "VM vm: migrate (live) to 198.51.100.9 via 203.0.113.9")
        self.vm.compute = self.source
        self.vm.save()
        self.dest.migration_address = "198.51.100.9"  # the host name itself
        self.migrate("live", live=True)
        self.assertEqual(Logs.objects.latest("id").message, "VM vm: migrate (live) to 198.51.100.9")

    def test_failure_is_logged_and_raised(self):
        with self.assertRaisesRegex(util.OperationError, "A shut-off VM cannot be migrated live"):
            self.migrate(util.OperationError("A shut-off VM cannot be migrated live"), live=True)
        self.assertEqual(rows(), [("VM vm: migrate to 198.51.100.9: A shut-off VM cannot be migrated live", False)])
