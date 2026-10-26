"""drbd_status runs ssh with the compute's login@hostname; a compute whose
values would inject an ssh option (an existing or bypassed row) is skipped,
and a compute that does not answer in time leaves the status unknown."""

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
            self.assertEqual(drbd_status(SimpleNamespace(user=None), 1), "None DRBD")
        self.assertEqual(run.call_args.kwargs["timeout"], DRBD_STATUS_TIMEOUT)


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
            "instances.views.subprocess.run", return_value=SimpleNamespace(stdout=stdout)
        ):
            return drbd_status(SimpleNamespace(user=None), 1)

    def test_a_vm_counts_only_its_own_resources(self):
        # "webserver" is another VM's resource; "web_data" is web's second disk
        self.assertEqual(self.status("web"), "Secondary/NOK")
        self.assertEqual(self.status("webserver"), "Primary/OK")

    def test_a_vm_without_a_resource_has_no_drbd(self):
        self.assertEqual(self.status("db"), "None DRBD")
