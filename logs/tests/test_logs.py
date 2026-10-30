from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from computes.models import Compute
from instances.models import Instance
from logs.audit import write
from logs.views import VM_LOG_ROWS

UUID = "12345678-1234-1234-1234-123456789012"


class VMLogsTestCase(TestCase):
    """The VM page's Logs tab: the rows of one VM, found by its UUID."""

    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser("admin_logs", "admin@example.com", "pw")
        self.normal_user = User.objects.create_user("normal_logs", "user@example.com", "pw")
        self.compute = Compute.objects.create(name="c1", hostname="192.0.2.1", type=1)
        self.instance = Instance.objects.create(compute=self.compute, name="test-vm", uuid=UUID)
        self.client.force_login(self.superuser)

    def shown(self, instance=None):
        response = self.client.get(reverse("vm_logs", args=[(instance or self.instance).pk]))
        self.assertEqual(response.status_code, 200)
        return [(row["message"], row["result"]) for row in response.json()]

    def test_only_the_latest_rows(self):
        for n in range(VM_LOG_ROWS + 1):
            write("admin", "c1", "test-vm", f"VM test-vm: row {n}", True, uuid=UUID)
        shown = self.shown()
        self.assertEqual(len(shown), VM_LOG_ROWS)
        self.assertEqual(shown[0][0], f"VM test-vm: row {VM_LOG_ROWS}")

    def test_rows_of_the_vm_with_their_result(self):
        write("admin", "c1", "test-vm", "VM test-vm: power on", True, uuid=UUID)
        write("admin", "c1", "test-vm", "VM test-vm: power off: not running", False, uuid=UUID)
        row = self.client.get(reverse("vm_logs", args=[self.instance.pk])).json()[0]
        self.assertEqual((row["user"], row["host"], row["instance"]), ("admin", "c1", "test-vm"))
        self.assertEqual(self.shown(), [("VM test-vm: power off: not running", "Failed"),
                                        ("VM test-vm: power on", "Done")])

    def test_a_vm_is_found_by_uuid_not_by_name(self):
        other = Compute.objects.create(name="c2", hostname="192.0.2.2", type=1)
        namesake = Instance.objects.create(compute=other, name="test-vm", uuid="87654321-4321-4321-4321-210987654321")
        write("admin", "c1", "old-name", "VM old-name: power on", True, uuid=UUID)  # before a rename
        write("admin", "c2", "test-vm", "VM test-vm: power on", True, uuid=namesake.uuid)
        write("admin", "c1", "test-vm", "Instance is created")  # a row from before the UUID column
        self.assertEqual(self.shown(), [("VM old-name: power on", "Done")])
        self.assertEqual(self.shown(namesake), [("VM test-vm: power on", "Done")])

    def test_one_vm_on_two_computes_shows_the_rows_of_both(self):
        other = Compute.objects.create(name="c2", hostname="192.0.2.2", type=1)
        moved = Instance.objects.create(compute=other, name="test-vm", uuid=UUID)
        write("admin", "c1", "test-vm", "VM test-vm: migrate (live) to 192.0.2.2", True, uuid=UUID)
        write("admin", "c2", "test-vm", "VM test-vm: power off", None, uuid=UUID)
        self.assertEqual(self.shown(moved), [("VM test-vm: power off", "Unknown"),
                                             ("VM test-vm: migrate (live) to 192.0.2.2", "Done")])
        self.assertEqual(self.shown(moved), self.shown())

    def test_unknown_vm(self):
        self.assertEqual(self.client.get(reverse("vm_logs", args=[999999])).status_code, 404)

    def test_non_superuser_forbidden(self):
        self.client.force_login(self.normal_user)
        response = self.client.get(reverse("vm_logs", args=[self.instance.pk]))
        self.assertNotEqual(response.status_code, 200)
