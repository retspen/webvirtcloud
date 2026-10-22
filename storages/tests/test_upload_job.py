"""An ISO upload is a job a request runs: each chunk request writes one chunk
and commits it on the job (spec: the chunk protocol)."""

import errno
import os
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from libvirt import VIR_ERR_NO_STORAGE_VOL, VIR_ERR_SYSTEM_ERROR, libvirtError

from computes.models import Compute
from operations import claims, jobs
from operations.models import Claim, Operation
from operations.worker import housekeeping
from storages.upload import IDLE, _atomic_finalize_local, _ssh_pool, _UploadTarget, _VolumeTarget, write_chunk
from vrtManager.connection import CONN_SOCKET, CONN_SSH, CONN_TCP, CONN_TLS

User = get_user_model()
KEY = "upload-key-0001"


class UploadTestCase(TestCase):
    """A pool on conn; the kind and the ending path open the same conn."""

    def setUp(self):
        self.compute = Compute.objects.create(name="up-c", hostname="192.0.2.30", login="root", password="", type=1)
        self.admin = User.objects.create_superuser("up_admin", "up_admin@example.com", "pw")
        self.conn = self.make_conn()
        self.opened = {}
        for target in ("storages.jobs.wvmStorage", "storages.upload.wvmStorage"):
            patcher = patch(target, return_value=self.conn)
            self.opened[target] = patcher.start()
            self.addCleanup(patcher.stop)

    def cancel_during_write(self, target_class):
        """The panel's cancel while this request writes: it finds the upload held."""
        write = target_class.write

        def cancelled(target, *args):
            Operation.objects.filter(kind="volume.upload").update(state=Operation.CANCELLING, cancel_requested=True)
            return write(target, *args)

        return patch.object(target_class, "write", cancelled)

    def send(self, index, data, total=3, size=9, name="disk.iso", key=KEY, user=None):
        return write_chunk(user or self.admin, self.conn, self.compute, "default", key,
                           {"name": name, "size": size, "chunks": total}, index, SimpleUploadedFile("chunk", data))

    def job(self):
        return Operation.objects.get(kind="volume.upload")


class LocalPool:
    def make_conn(self):
        self.pool = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.pool, ignore_errors=True)
        conn = MagicMock(conn=CONN_SOCKET)
        conn.get_target_path.return_value = self.pool
        conn.get_volumes.side_effect = lambda: sorted(os.listdir(self.pool))
        return conn

    def path(self, name="disk.iso"):
        return os.path.join(self.pool, name)

    def part(self, op):
        return self.path(f"disk.iso.wvc_upload_{op.pk.hex}.part")

    def read(self, path):
        with open(path, "rb") as stream:
            return stream.read()


class LocalUploadTests(LocalPool, UploadTestCase):
    def test_three_chunks_are_one_job(self):
        op = self.send(0, b"aaa")
        op.refresh_from_db()
        self.assertEqual((op.state, op.worker, op.progress_done, op.progress_total), (Operation.RUNNING, Operation.REQUEST, 3, 9))
        self.assertEqual(op.intent, {"chunk": 1, "created": True})
        self.assertEqual(set(Claim.objects.values_list("resource", "mode")), {
            (f"compute:{self.compute.pk}", "shared"), (f"pool:{self.compute.pk}:default", "shared"),
            (f"volume:{self.compute.pk}:default/disk.iso", "exclusive")})
        self.assertEqual(self.read(self.part(op)), b"aaa")
        self.send(1, b"bbb")
        op.refresh_from_db()
        self.assertEqual(op.progress_done, 6)
        self.send(2, b"ccc")
        op.refresh_from_db()
        self.assertEqual(op.state, Operation.SUCCEEDED)
        self.assertEqual(self.read(self.path()), b"aaabbbccc")
        self.assertFalse(os.path.exists(self.part(op)))
        self.assertFalse(Claim.objects.exists())
        self.assertEqual(Operation.objects.count(), 1)

    def test_a_duplicate_chunk_is_acknowledged_without_a_write(self):
        op = self.send(0, b"aaa")
        self.assertEqual(self.send(0, b"zzz").pk, op.pk)
        self.send(1, b"bbb")
        self.send(1, b"yyy")
        self.send(2, b"ccc")
        # the final answer was lost: the retry is answered success
        self.assertEqual(self.send(2, b"ccc").state, Operation.SUCCEEDED)
        self.assertEqual(self.read(self.path()), b"aaabbbccc")

    def test_a_duplicate_last_chunk_finishes_a_committed_upload(self):
        op = self.send(0, b"aaa", total=1, size=3)
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, finished_at=None)
        os.rename(self.path(), self.part(op))  # the request died before the rename
        self.assertEqual(self.send(0, b"aaa", total=1, size=3).state, Operation.SUCCEEDED)
        self.assertEqual(self.read(self.path()), b"aaa")

    def test_a_link_an_interrupted_rename_made_is_completed(self):
        op = self.committed_but_not_renamed()
        os.link(self.part(op), self.path())  # the request died after the link, before the unlink
        self.assertEqual(self.send(1, b"bbb", total=2, size=6).state, Operation.SUCCEEDED)
        self.assertEqual(os.listdir(self.pool), ["disk.iso"])
        self.assertEqual(self.read(self.path()), b"aaabbb")

    def test_an_image_gone_before_the_completion_fails_the_job(self):
        op = self.committed_but_not_renamed()
        os.unlink(self.part(op))
        with self.assertRaisesRegex(ValueError, "The uploaded image is missing"):
            self.send(1, b"bbb", total=2, size=6)
        op.refresh_from_db()
        self.assertEqual((op.state, op.error), (Operation.FAILED, "The uploaded image is missing"))
        self.assertFalse(Claim.objects.exists())

    def test_the_first_write_syncs_the_pool_directory_before_the_commit(self):
        synced = []
        with patch("storages.upload._fsync_dir", side_effect=lambda d: synced.append((d, self.job().progress_done))):
            self.send(0, b"aaa")
            self.send(1, b"bbb")
        self.assertEqual(synced, [(self.pool, None)])

    def test_sequence_and_session_are_checked(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            self.send(1, b"bbb")
        self.send(0, b"aaa")
        with self.assertRaisesRegex(ValueError, "sequence"):
            self.send(2, b"ccc")
        for changed in ({"size": 10}, {"total": 4}, {"name": "other.iso"}):
            with self.assertRaisesRegex(ValueError, "changed"):
                self.send(1, b"bbb", **changed)
        with self.assertRaises(jobs.SubmissionConflict):
            self.send(0, b"aaa", size=10)
        with self.assertRaisesRegex(ValueError, "declared file size"):
            self.send(1, b"bbbbbbb")
        self.assertEqual(self.job().progress_done, 3)

    def test_a_writer_that_died_mid_chunk_is_cut_back(self):
        op = self.send(0, b"aaa")
        with open(self.part(op), "ab") as stream:
            stream.write(b"UNCOMMITTED")
        self.send(1, b"bbb")
        self.assertEqual(self.read(self.part(op)), b"aaabbb")

    def test_an_interrupted_first_write_is_retried_from_the_start(self):
        chunk = SimpleUploadedFile("disk.iso", b"aaa")

        def interrupted():
            yield b"a"
            raise OSError("Interrupted first write")

        chunk.chunks = interrupted
        with self.assertRaises(OSError):
            write_chunk(self.admin, self.conn, self.compute, "default", KEY,
                        {"name": "disk.iso", "size": 9, "chunks": 3}, 0, chunk)
        op = self.job()
        self.assertEqual((op.intent, op.progress_done), ({"chunk": 0, "created": True}, None))
        self.assertEqual(self.read(self.part(op)), b"a")
        self.send(0, b"aaa")
        self.assertEqual(self.read(self.part(op)), b"aaa")

    def test_a_failure_before_the_part_file_is_retried(self):
        with patch("storages.upload._UploadTarget.write", side_effect=OSError("Cannot open part")):
            with self.assertRaises(OSError):
                self.send(0, b"aaa", total=1, size=3)
        self.send(0, b"aaa", total=1, size=3)
        self.assertEqual(self.read(self.path()), b"aaa")

    def test_a_name_taken_when_renameat2_finalizes_is_a_taken_name(self):
        part, final = self.path("disk.iso.part"), self.path()
        with open(part, "wb") as stream:
            stream.write(b"aaa")
        libc = MagicMock()
        libc.renameat2.return_value = -1
        with patch("os.link", side_effect=OSError(errno.EPERM, "no hard links")), \
                patch("ctypes.CDLL", return_value=libc), patch("ctypes.get_errno", return_value=errno.EEXIST):
            with self.assertRaises(FileExistsError):
                _atomic_finalize_local(part, final)
        self.assertEqual(self.read(part), b"aaa")

    def test_a_taken_name_is_refused_without_a_job(self):
        with open(self.path(), "wb") as stream:
            stream.write(b"mine")
        with self.assertRaises(FileExistsError):
            self.send(0, b"aaa")
        self.assertFalse(Operation.objects.exists())
        self.assertFalse(Claim.objects.exists())

    def test_a_destination_that_appears_before_the_rename_fails_the_job(self):
        op = self.send(0, b"aaa")
        self.send(1, b"bbb")
        with open(self.path(), "wb") as stream:
            stream.write(b"mine")
        with self.assertRaises(FileExistsError):
            self.send(2, b"ccc")
        op.refresh_from_db()
        self.assertEqual(op.state, Operation.FAILED)
        self.assertFalse(os.path.exists(self.part(op)))
        self.assertEqual(self.read(self.path()), b"mine")
        self.assertFalse(Claim.objects.exists())

    def test_cancel_deletes_the_part_file(self):
        op = self.send(0, b"aaa")
        op = jobs.cancel(op.pk, self.admin)
        self.assertEqual(op.state, Operation.CANCELLED)
        self.assertFalse(os.path.exists(self.part(op)))
        self.assertFalse(Claim.objects.exists())
        with self.assertRaises(ValueError):
            self.send(1, b"bbb")
        jobs.get_kind("volume.upload").cancel(op)  # already ended: nothing to do

    def test_a_cancel_during_a_chunk_is_ended_by_the_next_chunk(self):
        op = self.send(0, b"aaa")
        claims.admit({f"upload:{op.pk}": Claim.EXCLUSIVE}, holder="192.0.2.30:1:1")  # a chunk in flight
        op = jobs.cancel(op.pk, self.admin)
        self.assertEqual(op.state, Operation.CANCELLING)
        self.assertTrue(os.path.exists(self.part(op)))
        with self.assertRaises(claims.Busy):
            self.send(1, b"bbb")
        Claim.objects.filter(operation__isnull=True).delete()
        with self.assertRaisesRegex(ValueError, "cancelled"):
            self.send(1, b"bbb")
        op.refresh_from_db()
        self.assertEqual(op.state, Operation.CANCELLED)
        self.assertFalse(os.path.exists(self.part(op)))
        self.assertFalse(Claim.objects.exists())

    def test_a_cancel_during_a_write_ends_the_upload_after_it(self):
        op = self.send(0, b"aaa")
        with self.cancel_during_write(_UploadTarget), self.assertRaisesRegex(ValueError, "cancelled"):
            self.send(1, b"bbb")
        op.refresh_from_db()
        self.assertEqual(op.state, Operation.CANCELLED)
        self.assertEqual(os.listdir(self.pool), [])
        self.assertFalse(Claim.objects.exists())

    def test_a_cancel_during_the_last_write_comes_too_late(self):
        with self.cancel_during_write(_UploadTarget):
            self.send(0, b"aaa", total=1, size=3)
        self.assertEqual(self.job().state, Operation.SUCCEEDED)
        self.assertEqual(self.read(self.path()), b"aaa")

    def test_a_repeated_cancel_retries_the_stop(self):
        op = self.send(0, b"aaa")
        claims.admit({f"upload:{op.pk}": Claim.EXCLUSIVE}, holder="192.0.2.30:1:1")  # a request that died
        self.assertEqual(jobs.cancel(op.pk, self.admin).state, Operation.CANCELLING)
        Claim.objects.filter(operation__isnull=True).delete()
        self.assertEqual(jobs.cancel(op.pk, self.admin).state, Operation.CANCELLED)
        self.assertFalse(os.path.exists(self.part(op)))

    def committed_but_not_renamed(self):
        """Every chunk is in; the last request died before the rename."""
        self.send(0, b"aaa", total=2, size=6)
        with patch("storages.upload._complete", side_effect=OSError("the request died")):
            with self.assertRaises(OSError):
                self.send(1, b"bbb", total=2, size=6)
        return self.job()

    def test_a_cancel_of_an_upload_with_every_chunk_in_completes_it(self):
        op = jobs.cancel(self.committed_but_not_renamed().pk, self.admin)
        self.assertEqual(op.state, Operation.SUCCEEDED)
        self.assertEqual(os.listdir(self.pool), ["disk.iso"])
        self.assertEqual(self.read(self.path()), b"aaabbb")

    def test_a_retry_of_the_last_chunk_completes_a_cancelled_upload_with_every_chunk_in(self):
        op = self.committed_but_not_renamed()
        Operation.objects.filter(pk=op.pk).update(state=Operation.CANCELLING, cancel_requested=True)
        self.assertEqual(self.send(1, b"bbb", total=2, size=6).state, Operation.SUCCEEDED)
        self.assertEqual(self.read(self.path()), b"aaabbb")

    def test_an_idle_upload_with_every_chunk_in_is_completed(self):
        op = self.committed_but_not_renamed()
        Operation.objects.filter(pk=op.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=3601))
        housekeeping()
        op.refresh_from_db()
        self.assertEqual(op.state, Operation.SUCCEEDED)
        self.assertEqual(self.read(self.path()), b"aaabbb")

    def test_a_late_retry_of_the_last_chunk_completes_the_upload(self):
        op = self.committed_but_not_renamed()
        Operation.objects.filter(pk=op.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=3601))
        self.assertEqual(self.send(1, b"bbb", total=2, size=6).state, Operation.SUCCEEDED)
        self.assertEqual(self.read(self.path()), b"aaabbb")

    def test_ending_without_the_compute(self):
        op = self.send(0, b"aaa")
        with self.assertRaises(claims.Busy):  # the upload holds the compute
            self.compute.delete()
        Compute.objects.filter(pk=self.compute.pk).delete()  # the row gone without Compute.delete()
        op = jobs.cancel(op.pk, self.admin)
        self.assertEqual((op.state, op.error), (Operation.FAILED, "The compute was deleted"))

    def test_ending_before_anything_was_created_needs_no_connection(self):
        op = jobs.submit("volume.upload", self.admin, {"compute": self.compute.pk, "pool": "default",
                                                      "name": "disk.iso", "size": 9, "chunks": 3}, KEY)
        self.assertEqual(jobs.cancel(op.pk, self.admin).state, Operation.CANCELLED)
        self.opened["storages.upload.wvmStorage"].assert_not_called()

    def test_a_non_superuser_is_refused(self):
        user = User.objects.create_user("up_user", "up_user@example.com", "pw")
        with self.assertRaises(PermissionDenied):
            self.send(0, b"aaa", user=user)
        self.assertFalse(Operation.objects.exists())

    def test_an_idle_upload_expires(self):
        op = self.send(0, b"aaa")
        housekeeping()  # not idle: nothing is opened
        op.refresh_from_db()
        self.assertEqual(op.state, Operation.RUNNING)
        self.opened["storages.upload.wvmStorage"].assert_not_called()
        Operation.objects.filter(pk=op.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=3601))
        housekeeping()
        op.refresh_from_db()
        self.assertEqual((op.state, op.error), (Operation.FAILED, IDLE))
        self.assertFalse(os.path.exists(self.part(op)))
        self.assertFalse(Claim.objects.exists())

    def test_an_idle_cancelled_upload_expires_cancelled(self):
        op = self.send(0, b"aaa")
        Operation.objects.filter(pk=op.pk).update(state=Operation.CANCELLING, cancel_requested=True,
                                                  heartbeat_at=timezone.now() - timedelta(seconds=3601))
        housekeeping()
        op.refresh_from_db()
        self.assertEqual((op.state, op.error), (Operation.CANCELLED, ""))
        self.assertFalse(os.path.exists(self.part(op)))

    def test_a_chunk_after_the_idle_timeout_ends_the_job(self):
        op = self.send(0, b"aaa")
        Operation.objects.filter(pk=op.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=3601))
        with self.assertRaisesRegex(ValueError, "idle"):
            self.send(1, b"bbb")
        op.refresh_from_db()
        self.assertEqual((op.state, op.error), (Operation.FAILED, IDLE))
        self.assertFalse(os.path.exists(self.part(op)))

    def test_a_symlinked_part_file_is_refused(self):
        op = self.send(0, b"aaa")
        os.unlink(self.part(op))
        os.symlink(self.path("real.iso"), self.part(op))
        with self.assertRaises(PermissionError):
            self.send(1, b"bbb")
        self.assertFalse(os.path.exists(self.path("real.iso")))

    def test_path_traversal_is_refused(self):
        with patch("os.path.basename", side_effect=lambda x: x):
            with self.assertRaises(PermissionError):
                self.send(0, b"aaa", total=1, size=3, name="../../../evil.iso")
        self.assertFalse(os.path.exists(os.path.join(self.pool, "../../../evil.iso")))

    def test_the_name_must_be_an_iso(self):
        for name in ("image.img", ".iso", "..", "a\x00.iso"):
            with self.assertRaises(ValueError):
                self.send(0, b"aaa", name=name)
        self.send(0, b"aaa", total=1, size=3, name="image.ISO")
        self.assertTrue(os.path.exists(self.path("image.ISO")))


class SshUploadTests(UploadTestCase):
    base = "/var/lib/libvirt/images"

    def make_conn(self):
        self.addCleanup(_ssh_pool.close_all)
        conn = MagicMock(conn=CONN_SSH, host="192.0.2.31", login="root", passwd="pw")
        conn.get_target_path.return_value = self.base
        self.files = files = {}
        conn.get_volumes.side_effect = lambda: [p.rsplit("/", 1)[1] for p in files]
        patcher = patch("paramiko.SSHClient")
        self.ssh = patcher.start().return_value
        self.addCleanup(patcher.stop)
        sftp = self.ssh.open_sftp.return_value

        def lstat(path):
            if path not in files:
                raise FileNotFoundError(path)
            return MagicMock(st_mode=0o100644)

        class RemoteFile:
            """The SFTP file of a pipelined write; it is its own client."""

            MAX_REQUEST_SIZE = 32768
            handle = b"handle"
            sock = MagicMock(recv_ready=lambda: False)

            def __init__(self, path, mode):
                self.path = path
                if "w" in mode or path not in files:
                    files[path] = b""
                self.pos = 0

            @property
            def sftp(self):
                return self

            def _async_request(self, fileobj, kind, handle, offset, data):
                buf = bytearray(files[self.path])
                buf[offset:offset + len(data)] = data
                files[self.path] = bytes(buf)

            def _finish_responses(self, fileobj):
                pass

            def _check_exception(self):
                pass

            def seek(self, pos):
                self.pos = pos

            def truncate(self, size):
                files[self.path] = files[self.path][:size]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        def rename(src, dst):
            if dst in files:
                raise OSError("Failure")  # what OpenSSH answers
            files[dst] = files.pop(src)

        sftp.lstat.side_effect = lstat
        sftp.open.side_effect = RemoteFile
        sftp.rename.side_effect = rename
        sftp.remove.side_effect = lambda path: files.pop(path)
        return conn

    def part(self, op):
        return f"{self.base}/disk.iso.wvc_upload_{op.pk.hex}.part"

    def test_three_chunks_over_sftp(self):
        op = self.send(0, b"aaa")
        self.assertEqual(self.ssh.connect.call_args.kwargs["timeout"], 10)
        self.files[self.part(op)] += b"UNCOMMITTED"  # a writer died after its write
        self.send(1, b"bbb")
        self.send(2, b"ccc")
        self.send(2, b"ccc")
        op.refresh_from_db()
        self.assertEqual(op.state, Operation.SUCCEEDED)
        self.assertEqual(self.files, {f"{self.base}/disk.iso": b"aaabbbccc"})
        # one connection for the chunks, an SFTP session for each that wrote
        self.ssh.connect.assert_called_once()
        self.assertEqual(self.ssh.open_sftp.call_count, 3)

    def test_a_destination_that_appears_before_the_rename_fails_the_job(self):
        op = self.send(0, b"aaa")
        self.send(1, b"bbb")
        self.files[f"{self.base}/disk.iso"] = b"mine"
        with self.assertRaises(FileExistsError):
            self.send(2, b"ccc")
        op.refresh_from_db()
        self.assertEqual(op.state, Operation.FAILED)
        self.assertEqual(self.files, {f"{self.base}/disk.iso": b"mine"})

    def test_a_rename_whose_answer_was_lost_is_completed(self):
        rename = self.ssh.open_sftp.return_value.rename.side_effect

        def lost(src, dst):
            rename(src, dst)
            raise OSError("Failure")

        self.ssh.open_sftp.return_value.rename.side_effect = lost
        self.assertEqual(self.send(0, b"aaa", total=1, size=3).state, Operation.SUCCEEDED)
        self.assertEqual(self.files, {f"{self.base}/disk.iso": b"aaa"})

    def test_cancel_deletes_the_remote_part_file(self):
        op = self.send(0, b"aaa")
        self.assertEqual(jobs.cancel(op.pk, self.admin).state, Operation.CANCELLED)
        self.assertEqual(self.files, {})

    def test_path_traversal_is_refused(self):
        with patch("os.path.basename", side_effect=lambda x: x):
            with self.assertRaises(PermissionError):
                self.send(0, b"aaa", total=1, size=3, name="../../../evil.iso")
        self.assertEqual(self.files, {})


class LibvirtStreamUploadTests(UploadTestCase):
    def make_conn(self):
        conn = MagicMock(conn=CONN_TCP)
        self.volumes = volumes = {}
        conn.get_volumes.side_effect = lambda: list(volumes)

        def get_volume(name):
            if name not in volumes:
                error = libvirtError("Storage volume not found")
                error.err = (VIR_ERR_NO_STORAGE_VOL,)
                raise error
            return volumes[name]

        conn.get_volume.side_effect = get_volume

        def create(xml, flags):
            from xml.etree import ElementTree

            root = ElementTree.fromstring(xml)
            name = root.findtext("name")
            self.assertNotIn(name, volumes)
            self.assertEqual((root.findtext("capacity"), root.find("target/format").get("type")), ("9", "raw"))
            volumes[name] = MagicMock()
            volumes[name].delete.side_effect = lambda flags: volumes.pop(name)

        conn.pool.createXML.side_effect = create
        conn.wvm.newStream.return_value.send.side_effect = len
        return conn

    def test_chunks_stream_at_their_offsets(self):
        self.send(0, b"aaa")
        self.send(0, b"aaa")
        volume = self.volumes["disk.iso"]
        self.send(1, b"bbb")
        self.send(2, b"ccc")
        self.send(2, b"ccc")
        self.conn.pool.createXML.assert_called_once()
        self.assertEqual([c.args[1:] for c in volume.upload.call_args_list], [(0, 3, 0), (3, 3, 0), (6, 3, 0)])
        self.assertEqual(self.job().state, Operation.SUCCEEDED)

    def test_tls_uses_the_stream(self):
        self.conn.conn = CONN_TLS
        self.send(0, b"aaaaaaaaa", total=1)
        self.volumes["disk.iso"].upload.assert_called_once()

    def test_a_failed_stream_aborts_and_the_chunk_is_retried(self):
        stream = self.conn.wvm.newStream.return_value
        stream.send.side_effect = [1, OSError("connection lost")]
        with self.assertRaises(OSError):
            self.send(0, b"aaa")
        stream.abort.assert_called_once()
        stream.send.side_effect = len
        self.send(0, b"aaa")
        self.conn.pool.createXML.assert_called_once()
        self.assertEqual(self.job().progress_done, 3)

    def test_an_idle_upload_with_every_chunk_in_is_kept(self):
        self.send(0, b"aaa")
        self.send(1, b"bbb")
        with patch("storages.upload._complete", side_effect=OSError("the request died")):
            with self.assertRaises(OSError):
                self.send(2, b"ccc")
        Operation.objects.filter(pk=self.job().pk).update(heartbeat_at=timezone.now() - timedelta(seconds=3601))
        housekeeping()
        self.assertEqual(self.job().state, Operation.SUCCEEDED)
        self.assertEqual(list(self.volumes), ["disk.iso"])

    def test_a_cancel_during_the_last_write_keeps_the_volume(self):
        with self.cancel_during_write(_VolumeTarget):
            self.send(0, b"aaaaaaaaa", total=1)
        self.assertEqual((self.job().state, list(self.volumes)), (Operation.SUCCEEDED, ["disk.iso"]))

    def test_a_volume_gone_before_the_completion_fails_the_job(self):
        self.send(0, b"aaa")
        self.send(1, b"bbb")
        with patch("storages.upload._complete", side_effect=OSError("the request died")):
            with self.assertRaises(OSError):
                self.send(2, b"ccc")
        del self.volumes["disk.iso"]
        Operation.objects.filter(pk=self.job().pk).update(heartbeat_at=timezone.now() - timedelta(seconds=3601))
        housekeeping()
        self.assertEqual((self.job().state, self.job().error), (Operation.FAILED, "The uploaded image is missing"))

    def test_a_failed_volume_lookup_is_raised(self):
        error = libvirtError("connection lost")
        error.err = (VIR_ERR_SYSTEM_ERROR,)
        self.conn.get_volume.side_effect = error
        with self.assertRaises(libvirtError):
            _VolumeTarget(self.conn, "disk.iso", 9).present()

    def test_cancel_deletes_the_volume(self):
        op = self.send(0, b"aaa")
        self.assertEqual(jobs.cancel(op.pk, self.admin).state, Operation.CANCELLED)
        self.assertEqual(self.volumes, {})

    def test_an_existing_volume_is_kept(self):
        self.volumes["disk.iso"] = MagicMock()
        with self.assertRaises(FileExistsError):
            self.send(0, b"aaa")
        self.conn.pool.createXML.assert_not_called()


class UploadViewTests(LocalPool, UploadTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("storages.views.wvmStorage", return_value=self.conn)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_login(self.admin)
        self.url = reverse("storage", args=[self.compute.pk, "default"])

    def post(self, index=0, data=b"aaa", total=1, size="3", name="disk.iso", key=KEY, **fields):
        payload = {"iso_upload": "1", "file": SimpleUploadedFile(name, data), "file_name": name,
                   "chunk_index": str(index), "total_chunks": str(total), "file_size": size, "upload_id": key}
        payload.update(fields)
        return self.client.post(self.url, {k: v for k, v in payload.items() if v is not None})

    def test_the_answer_carries_the_job(self):
        first = self.post(0, total=2, size="6")
        self.assertEqual(first.status_code, 200)
        op = self.job()
        self.assertEqual(first.json(), {"success": True, "job": str(op.pk)})
        self.assertEqual(self.client.session["operations_shown"],
                         [{"resource": f"pool:{self.compute.pk}:default", "id": str(op.pk)}])
        last = self.post(1, data=b"bbb", total=2, size="6").json()
        self.assertEqual((last["success"], last["job"]), (True, str(op.pk)))
        self.assertEqual(last, {"success": True, "job": str(op.pk)})

    def test_field_errors(self):
        for fields, status, error in (
            ({"name": "notes.txt"}, 400, "Only .iso files"),
            ({"file": None}, 400, "No file chunk was submitted"),
            ({"file_name": "..\x00.."}, 400, "Invalid file name"),
            ({"key": None}, 400, "no valid submission key"),
            ({"size": None}, 400, "Invalid file size"),
            ({"size": "0"}, 400, "Invalid file size"),
            ({"index": 1}, 400, "Invalid chunk index"),
        ):
            with self.subTest(fields=fields):
                kwargs = {k: v for k, v in fields.items() if k in ("name", "size", "key", "index")}
                extra = {k: v for k, v in fields.items() if k not in kwargs}
                response = self.post(**kwargs, **extra)
                self.assertEqual(response.status_code, status)
                self.assertIn(error, response.json()["error"])
        self.assertFalse(Operation.objects.exists())

    def test_a_taken_name(self):
        with open(self.path(), "wb") as stream:
            stream.write(b"mine")
        response = self.post()
        self.assertEqual((response.status_code, response.json()["error"]), (400, "ISO image already exists"))

    def test_an_unexpected_failure_is_logged(self):
        with patch("storages.views.write_chunk", side_effect=OSError("disk gone")), \
             self.assertLogs("storages.views", "ERROR") as logs:
            response = self.post()
        self.assertEqual((response.status_code, response.json()["error"]), (500, "disk gone"))
        self.assertIn("OSError: disk gone", logs.output[0])

    def test_a_busy_session_is_retried(self):
        self.post(0, total=2, size="6")
        claims.admit({f"upload:{self.job().pk}": Claim.EXCLUSIVE}, holder="192.0.2.30:1:1")
        response = self.post(1, data=b"bbb", total=2, size="6")
        self.assertEqual((response.status_code, response.json()["error"]),
                         (429, "Upload session is busy. Please retry."))

    def test_a_name_another_upload_holds_is_refused_with_the_reason(self):
        self.post(0, total=2, size="6")
        response = self.post(0, total=2, size="6", key="upload-key-0002")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Upload ISO image is running on this resource", response.json()["error"])

    def test_submission_keys_are_per_user(self):
        self.post(0, total=2, size="6")
        other = User.objects.create_superuser("up_other", "up_other@example.com", "pw")
        self.client.force_login(other)
        response = self.post(1, data=b"bbb", total=2, size="6")
        self.assertEqual(response.status_code, 400)
        self.assertIn("not found", response.json()["error"])
        response = self.post(0, total=1, size="3", name="other.iso")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Operation.objects.filter(submission_key=KEY).count(), 2)
        self.assertNotEqual(response.json()["job"], str(Operation.objects.get(user=self.admin).pk))

