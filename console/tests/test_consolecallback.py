"""The serial console worker: a paste reaches the VM whole although its
stream takes it in parts or is busy, and the stream is dropped once."""

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

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

    def test_a_closed_client_ends_the_worker(self):
        with patch.object(self.cb.os, "read", return_value=b""):
            self.cb.from_client(None, 0, None, self.console)
        self.assertFalse(self.console.running)
        self.console.stream.send.assert_not_called()
