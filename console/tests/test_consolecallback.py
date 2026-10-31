"""The serial console worker: a paste reaches the VM whole although its
stream takes it in parts or is busy, the stream is dropped once, and a VM
that stops is reported."""

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase as DjangoTestCase

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance

CONSOLECALLBACK = Path(__file__).resolve().parent.parent.parent / "conf" / "daemon" / "consolecallback"


def load():
    loader = SourceFileLoader("consolecallback_under_test", str(CONSOLECALLBACK))
    module = module_from_spec(spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


class ConsoleWorkerTests(TestCase):
    def setUp(self):
        self.cb = load()
        self.console = MagicMock(running=True)

    def test_a_paste_reaches_the_vm_whole(self):
        received = []

        def send(data):
            if len(received) % 2 == 0:  # busy every other time
                received.append(b"")
                return -2
            received.append(data[:3])  # takes three bytes at a time
            return 3

        self.console.stream.send.side_effect = send
        with patch.object(self.cb.os, "read", return_value=b"echo hello\r"), patch.object(self.cb.time, "sleep"):
            self.cb.from_client(None, 0, None, self.console)
        self.assertEqual(b"".join(received), b"echo hello\r")

    def test_a_vm_that_takes_nothing_does_not_hold_the_console_for_ever(self):
        self.console.stream.send.return_value = -2
        clock = iter(range(0, 100))
        with patch.object(self.cb.os, "read", return_value=b"x"), patch.object(self.cb.time, "sleep"), \
                patch.object(self.cb.time, "monotonic", side_effect=lambda: next(clock)):
            self.cb.from_client(None, 0, None, self.console)
        self.assertLessEqual(self.console.stream.send.call_count, self.cb.SEND_WAIT + 1)

    def test_the_stream_is_dropped_once(self):
        console = self.cb.Console.__new__(self.cb.Console)
        console.stream = stream = MagicMock()
        console.close_stream()
        console.close_stream()  # the other thread, a moment later
        stream.abort.assert_called_once_with()

    def test_a_vm_that_stops_is_reported_although_its_stream_ended_first(self):
        console = self.cb.Console.__new__(self.cb.Console)
        console.domain = MagicMock()
        console.stream = None  # from_vm dropped it at the stream's end
        console.active = True
        console.domain.state.return_value = [self.cb.libvirt.VIR_DOMAIN_SHUTOFF]
        with patch.object(self.cb, "say") as say:
            console.check()
            console.check()
        say.assert_called_once_with("The VM is not running: its console opens again when it starts")

    def test_a_vm_that_stops_while_its_console_reopens_is_reported(self):
        console = self.cb.Console.__new__(self.cb.Console)
        console.domain, console.connection = MagicMock(), MagicMock()
        console.stream = None
        console.active = True
        console.domain.state.return_value = [self.cb.libvirt.VIR_DOMAIN_RUNNING]
        console.domain.openConsole.side_effect = self.cb.libvirt.libvirtError("domain is not running")
        console.domain.isActive.return_value = 0
        with patch.object(self.cb, "say") as say:
            console.check()
        say.assert_called_once_with("The VM is not running: its console opens again when it starts")
        self.assertIsNone(console.stream)

    def test_a_closed_client_ends_the_worker(self):
        with patch.object(self.cb.os, "read", return_value=b""):
            self.cb.from_client(None, 0, None, self.console)
        self.assertFalse(self.console.running)
        self.console.stream.send.assert_not_called()


class AccessTests(DjangoTestCase):
    """The worker ends a session whose user may no longer open the console."""

    def test_an_owner_removed_meanwhile_loses_the_console(self):
        cb = load()
        compute = Compute.objects.create(name="c", hostname="192.0.2.1", login="u", password="p", type=1)
        vm = Instance.objects.create(compute=compute, name="vm-a", uuid="11111111-0000-0000-0000-000000000009")
        owner = get_user_model().objects.create_user("owner", password="pw")
        ownership = UserInstance.objects.create(user=owner, instance=vm)
        with patch.object(cb.db.connection, "close"):  # the test's transaction keeps its connection
            self.assertTrue(cb.may_still_open(owner.pk, vm))
            ownership.delete()
            self.assertFalse(cb.may_still_open(owner.pk, vm))
            self.assertFalse(cb.may_still_open(999999, vm))
