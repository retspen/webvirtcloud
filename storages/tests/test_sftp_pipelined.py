"""ISO chunks go to an SSH compute as pipelined SFTP writes. paramiko's own
pipelined writes drop their errors, so the upload registers each write to
the file: every answer, in whatever order it comes, reaches the file and an
error is raised. Checked with paramiko's real client and file, on a fake
transport."""

import logging
import threading
import unittest
from unittest.mock import MagicMock

import paramiko
from django.core.files.uploadedfile import SimpleUploadedFile
from paramiko.message import Message
from paramiko.sftp import CMD_STATUS, CMD_WRITE, SFTP_FAILURE, SFTP_OK

from storages.upload import _UploadTarget
from vrtManager.connection import CONN_SSH


class Client(paramiko.SFTPClient):
    """paramiko's SFTPClient without a channel. The server answers once it is
    asked for an answer, all requests so far in the given order, and fails
    the request numbered fail_at."""

    def __init__(self, order=None, fail_at=None, answer_early=False):
        self._lock = threading.Lock()
        self._expecting = {}
        self.request_number = 1
        self.logger = logging.getLogger("test_sftp_pipelined")
        self.ultra_debug = False
        self.order, self.fail_at = order, fail_at
        self.written = {}
        self.answers = []
        # answer_early: an answer is ready as soon as its request is sent
        self.sock = MagicMock(recv_ready=lambda: answer_early and bool(self.answers))

    def _send_packet(self, kind, packet):
        message = Message(packet.asbytes())
        number = message.get_int()
        if kind == CMD_WRITE:
            message.get_string()  # handle
            offset = message.get_int64()
            self.written[offset] = message.get_string()
        self.answers.append(number)  # the close too

    def _read_packet(self):
        if self.order is not None:
            self.answers = [self.answers[i] for i in self.order(len(self.answers))]
            self.order = None
        number = self.answers.pop(0)
        answer = Message()
        answer.add_int(number)
        answer.add_int(SFTP_FAILURE if number == self.fail_at else SFTP_OK)
        answer.add_string("Failure" if number == self.fail_at else "")
        answer.add_string("")
        return CMD_STATUS, answer.asbytes()


SIZE = 10 * paramiko.SFTPFile.MAX_REQUEST_SIZE


def upload(client):
    target = _UploadTarget(MagicMock(conn=CONN_SSH, host="192.0.2.1"), "/pool", "x.iso", "id")
    target.sftp = MagicMock(open=lambda path, mode: paramiko.SFTPFile(client, b"handle", "w"))
    data = bytes(range(256)) * (SIZE // 256)
    return target.write(SimpleUploadedFile("x.iso", data), 0, new=True), data


class PipelinedWriteTestCase(unittest.TestCase):
    def test_all_writes_are_sent_then_answered_in_any_order(self):
        for name, order in (("in order", None), ("reversed", lambda n: reversed(range(n)))):
            with self.subTest(name):
                client = Client(order=order)
                written, data = upload(client)
                self.assertEqual(written, SIZE)
                self.assertEqual(b"".join(client.written[k] for k in sorted(client.written)), data)
                self.assertEqual(client._expecting, {})  # every answer was taken

    def test_answers_read_while_sending(self):
        client = Client(answer_early=True)
        written, data = upload(client)
        self.assertEqual(b"".join(client.written[k] for k in sorted(client.written)), data)
        self.assertEqual(client._expecting, {})

    def test_an_error_of_any_write_is_raised(self):
        for name, client in (
            ("in order", lambda: Client(fail_at=4)),
            ("reversed", lambda: Client(order=lambda n: reversed(range(n)), fail_at=4)),
            ("read while sending", lambda: Client(fail_at=4, answer_early=True)),
        ):
            with self.subTest(name):
                with self.assertRaisesRegex(IOError, "Failure"):
                    upload(client())
