"""drbd_status runs ssh with the compute's login@hostname; a compute whose
values would inject an ssh option (an existing or bypassed row) is skipped,
and a compute that does not answer in time, or an ssh that fails, leaves
the status unknown, not "None DRBD"."""

import subprocess
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

from appsettings.models import AppSettings
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from instances.views import DRBD_STATUS_TIMEOUT, _valid_ssh_target, drbd_status


class DrbdTargetTestCase(unittest.TestCase):
    def test_valid_target(self):
        self.assertTrue(_valid_ssh_target(SimpleNamespace(login="root", hostname="192.0.2.1")))

    def test_option_injection_is_skipped(self):
        for login, hostname in (("-oProxyCommand=x", "192.0.2.1"), ("root", "-x"), ("root", "a b")):
            with self.subTest(login=login, hostname=hostname):
                self.assertFalse(_valid_ssh_target(SimpleNamespace(login=login, hostname=hostname)))

    def test_a_compute_that_does_not_answer_leaves_the_status_unknown(self):
        vm = SimpleNamespace(name="vm1", compute=SimpleNamespace(type=2, login="root", hostname="192.0.2.1"))
        with patch("instances.views.get_instance", return_value=vm), patch(
            "instances.views.subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", DRBD_STATUS_TIMEOUT)
        ) as run:
            self.assertEqual(drbd_status(SimpleNamespace(user=None), 1), "Unknown")
        self.assertEqual(run.call_args.kwargs["timeout"], DRBD_STATUS_TIMEOUT)

    def test_a_failed_ssh_leaves_the_status_unknown(self):
        vm = SimpleNamespace(name="vm1", compute=SimpleNamespace(type=2, login="root", hostname="192.0.2.1"))
        with patch("instances.views.get_instance", return_value=vm), patch(
            "instances.views.subprocess.run", return_value=SimpleNamespace(returncode=255, stdout="")
        ):
            self.assertEqual(drbd_status(SimpleNamespace(user=None), 1), "Unknown")


STATUS = """webserver role:Primary
  disk:UpToDate
web role:Secondary
  disk:UpToDate
web_data role:Secondary
  disk:Outdated
"""


class DrbdStatusTestCase(unittest.TestCase):
    def status(self, name, stdout=STATUS):
        vm = SimpleNamespace(name=name, compute=SimpleNamespace(type=2, login="root", hostname="192.0.2.1"))
        with patch("instances.views.get_instance", return_value=vm), patch(
            "instances.views.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=stdout)
        ):
            return drbd_status(SimpleNamespace(user=None), 1)

    def test_a_vm_counts_only_its_own_resources(self):
        # "webserver" is another VM's resource; "web_data" is web's second disk
        self.assertEqual(self.status("web"), "Secondary/NOK")
        self.assertEqual(self.status("webserver"), "Primary/OK")

    def test_a_vm_without_a_resource_has_no_drbd(self):
        self.assertEqual(self.status("db"), "None DRBD")


class DrbdListTestCase(TestCase):
    """The VM list reads each SSH host's DRBD state once, for all its VMs:
    the VM page alone left the list showing an old state."""

    def test_the_list_shows_each_vms_state_from_one_read_per_host(self):
        AppSettings.objects.filter(key="VM_DRBD_STATUS").update(value="True")
        host = Compute.objects.create(name="drbd-host", hostname="192.0.2.1", type=2, login="root", password="")
        for number, name in enumerate(("web", "webserver", "db")):
            Instance.objects.create(compute=host, name=name, uuid=f"11111111-1111-1111-1111-00000000000{number}")
        self.client.force_login(get_user_model().objects.create_superuser("drbd", "d@example.com", "pw"))
        with patch("instances.views.refresh_instance_database"), \
                patch.object(Compute, "status", new_callable=PropertyMock, return_value=True), \
                patch.object(Instance, "info", new_callable=PropertyMock, return_value=None), \
                patch.object(Compute, "proxy", new_callable=PropertyMock,
                             return_value=MagicMock(**{"get_domain_rows.return_value": {}})), \
                patch("instances.views.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=STATUS)) as run:
            self.assertEqual(self.client.get(reverse("instances:index")).status_code, 200)
        run.assert_called_once()
        self.assertEqual(dict(Instance.objects.values_list("name", "drbd")),
                         {"web": "Secondary/NOK", "webserver": "Primary/OK", "db": "None DRBD"})

    def test_hosts_are_asked_at_once(self):
        # a host that does not answer delays the list by one timeout, not one per host
        AppSettings.objects.filter(key="VM_DRBD_STATUS").update(value="True")
        for number in range(3):
            host = Compute.objects.create(name=f"drbd-{number}", hostname=f"192.0.2.{number + 1}", type=2, login="root",
                                          password="")
            Instance.objects.create(compute=host, name=f"vm{number}", uuid=f"11111111-1111-1111-1111-00000000001{number}")
        self.client.force_login(get_user_model().objects.create_superuser("drbd", "d@example.com", "pw"))

        def slow(*args, **kwargs):
            time.sleep(0.5)
            return SimpleNamespace(returncode=0, stdout="")

        start = time.monotonic()
        with patch("instances.views.refresh_instance_database"), \
                patch.object(Compute, "status", new_callable=PropertyMock, return_value=True), \
                patch.object(Instance, "info", new_callable=PropertyMock, return_value=None), \
                patch.object(Compute, "proxy", new_callable=PropertyMock,
                             return_value=MagicMock(**{"get_domain_rows.return_value": {}})), \
                patch("instances.views.subprocess.run", side_effect=slow) as run:
            self.client.get(reverse("instances:index"))
        self.assertEqual(run.call_count, 3)
        self.assertLess(time.monotonic() - start, 1.4)
