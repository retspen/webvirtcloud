"""Secret changes write rows on the Logs page; a secret's value never does."""

from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from vrtManager.util import OperationError

from logs.models import Logs

UUID = "8f2c0000-0000-4000-8000-000000000009"
VALUE = "s3cr3t-value"


def rows():
    return list(Logs.objects.order_by("id").values_list("message", "success"))


class SecretRowTests(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="c1", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("audit-admin", "a@example.com", "pw"))
        Logs.objects.all().delete()  # the login's row
        self.url = reverse("virtsecrets", args=[self.compute.id])
        patcher = patch("virtsecrets.views.wvmSecrets")
        self.conn = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.conn.get_secrets_info.return_value = []

    def test_secret_actions(self):
        self.client.post(self.url, {"create": "", "private": "on", "usage_type": "ceph", "usage": "client.admin",
                                    "value": VALUE})
        self.client.post(self.url, {"set_value": "", "uuid": UUID, "value": VALUE})
        self.client.post(self.url, {"delete": "", "uuid": UUID})
        self.assertEqual(rows(), [
            ("Secret ceph client.admin: add", True),
            (f"Secret {UUID}: set value", True),
            (f"Secret {UUID}: delete", True),
        ])
        self.assertEqual(set(Logs.objects.values_list("host", flat=True)), {"c1"})

    def test_a_secret_value_is_never_logged(self):
        # an unexpected error naming the value is raised, its row names only the error's class
        self.conn.set_secret_value.side_effect = ValueError(f"bad value {VALUE}")
        with self.assertRaises(ValueError):
            self.client.post(self.url, {"set_value": "", "uuid": UUID, "value": VALUE})
        self.assertEqual(rows(), [(f"Secret {UUID}: set value: ValueError", False)])
        self.conn.set_secret_value.side_effect = OperationError("A Ceph key is base64 text")
        with patch.object(Logs.objects, "create", side_effect=RuntimeError("db down")), \
                self.assertLogs("logs.audit", "WARNING") as logged:
            self.client.post(self.url, {"set_value": "", "uuid": UUID, "value": VALUE})
        self.assertNotIn(VALUE, "\n".join(logged.output))
        self.assertIn(f"Secret {UUID}: set value", "\n".join(logged.output))

    def test_a_refused_secret_delete(self):
        self.conn.delete_secret.side_effect = OperationError(f"Secret {UUID} is used by VMs db-2")
        self.client.post(self.url, {"delete": "", "uuid": UUID})
        self.assertEqual(rows(), [(f"Secret {UUID}: delete: Secret {UUID} is used by VMs db-2", False)])
