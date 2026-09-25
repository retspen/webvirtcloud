import json
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from computes.models import Compute
from instances.models import Instance
from logs.models import Logs
from logs.views import addlogmsg


class LogsTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="admin_logs", email="admin@example.com", password="adminpassword"
        )
        self.normal_user = User.objects.create_user(
            username="normal_logs", email="user@example.com", password="userpassword"
        )
        self.compute = Compute.objects.create(
            name="local_compute",
            hostname="localhost",
            type=1,
        )
        self.instance = Instance.objects.create(
            compute=self.compute,
            name="test-vm",
            uuid="12345678-1234-1234-1234-123456789012",
        )

    def test_addlogmsg(self):
        addlogmsg("admin", "localhost", "test-vm", "Started VM")
        log = Logs.objects.filter(instance="test-vm").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, "admin")
        self.assertEqual(log.host, "localhost")
        self.assertEqual(log.message, "Started VM")

    def test_vm_logs_superuser_access(self):
        addlogmsg("admin", "localhost", "test-vm", "Created VM")
        client = Client()
        client.login(username="admin_logs", password="adminpassword")

        response = client.get(reverse("vm_logs", args=["test-vm"]))
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content.decode("utf-8"))
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["user"], "admin")
        self.assertEqual(data[0]["message"], "Created VM")
        self.assertEqual(data[0]["instance"], "test-vm")

    def test_vm_logs_non_superuser_forbidden(self):
        client = Client()
        client.login(username="normal_logs", password="userpassword")

        response = client.get(reverse("vm_logs", args=["test-vm"]))
        # superuser_only decorator redirects non-superusers to index or login
        self.assertNotEqual(response.status_code, 200)
