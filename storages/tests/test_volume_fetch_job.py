"""A volume made from a URL (an ISO or a disk image) by a job: the pool page
queues it, the worker streams the file into a new volume of the pool through
libvirt, telling its progress; a cancel or a failure deletes what it wrote."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from computes.models import Compute
from operations.jobs import Cancelled, Context
from operations.models import Operation, acquire
from storages.jobs import FetchVolume, open_download
from vrtManager import util
from vrtManager.storage import wvmStorage

URL = "https://images.example.com/rocky-10.qcow2"


def answer(chunks, size=None, status=200, headers=None):
    body = MagicMock(status=status, reason="OK")
    body.headers = {"Content-Length": str(size if size is not None else sum(map(len, chunks))), **(headers or {})}
    if size == -1:
        del body.headers["Content-Length"]
    body.stream.return_value = iter(chunks)
    return body


class FetchJobTestCase(TransactionTestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="fe-c", hostname="192.0.2.21", login="root", password="", type=1)
        self.client.force_login(get_user_model().objects.create_superuser("fe_admin", "f@example.com", "pw"))
        patcher = patch("storages.jobs.wvmStorage")
        self.stg = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.stg.get_volumes.return_value = []
        self.stg.get_type.return_value = "dir"
        self.stg.get_size.return_value = [10 * 2**30, 5 * 2**30]
        self.stg.write_volume.side_effect = lambda name, size, chunks: sum(len(c) for c in chunks)
        self.stg.new_raw_volume.return_value = None
        page = patch("storages.views.wvmStorage").start().return_value  # the pool page's own connection
        page.is_active.return_value = False
        page.get_size.return_value = (1, 1)
        self.addCleanup(patch.stopall)

    def queue(self, url=URL, name=""):
        self.client.post(reverse("storage", args=[self.compute.pk, "images"]),
                         {"fetch_volume": "1", "url": url, "name": name, "submission_key": "key-fetch001"})
        return Operation.objects.filter(kind="volume.fetch").first()

    def run_job(self, op, chunks, size=None):
        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        ctx = Context(op, SimpleNamespace(identity="wvc-test:1:a"))
        with patch("storages.jobs.open_download", return_value=answer(chunks, size)) as get:
            FetchVolume().precheck(op, ctx)
            result = FetchVolume().run(op, ctx)
        self.assertEqual(get.call_args.args[0], URL)
        return result

    def test_the_page_queues_it_and_the_worker_streams_it(self):
        op = self.queue()
        self.assertEqual((op.params["url"], op.params["name"]), (URL, "rocky-10.qcow2"))  # named by the URL
        self.run_job(op, [b"ab", b"cd"])
        self.stg.new_raw_volume.assert_called_once_with("rocky-10.qcow2", 4)
        name, size, _chunks = self.stg.write_volume.call_args.args
        self.assertEqual((name, size), ("rocky-10.qcow2", 4))
        op.refresh_from_db()
        self.assertEqual((op.intent["done"], op.intent["total"]), (4, 4))

    def test_the_pool_page_offers_it_for_a_pool_of_files(self):
        page = patch("storages.views.wvmStorage").start().return_value
        page.is_active.return_value = True
        page.get_size.return_value = (10, 4)
        page.update_volumes.return_value = []
        for kind, offered in (("dir", True), ("logical", False)):
            with self.subTest(kind=kind):
                page.get_type.return_value = kind
                response = self.client.get(reverse("storage", args=[self.compute.pk, "images"]))
                self.assertEqual('name="fetch_volume"' in response.content.decode(), offered)

    def test_what_is_refused_when_asked(self):
        for url, name, why in (("ftp://example.com/a.iso", "", "http"), (URL, "../x", "name"),
                               ("https://example.com/", "", "name"), ("http://[::1/a.iso", "", "unreadable")):
            with self.subTest(url=url, name=name):
                Operation.objects.all().delete()
                self.assertIsNone(self.queue(url, name), why)
        self.stg.get_volumes.return_value = ["rocky-10.qcow2"]  # taken
        self.assertIsNone(self.queue())
        self.stg.get_volumes.return_value = []
        self.stg.get_type.return_value = "logical"  # not a pool of files
        self.assertIsNone(self.queue())

    def test_a_file_without_a_size_or_too_big_is_refused_before_writing(self):
        op = self.queue()
        with self.assertRaisesRegex(util.OperationError, "does not tell the file's size"):
            self.run_job(op, [b"ab"], size=-1)
        with self.assertRaisesRegex(util.OperationError, "free"):
            self.run_job(op, [b"ab"], size=6 * 2**30)
        self.stg.write_volume.assert_not_called()

    def test_an_address_that_fails_says_why(self):
        op = self.queue()
        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        failing = util.OperationError("The server answered 404 Not Found, not the whole file")
        with patch("storages.jobs.open_download", side_effect=failing), \
                self.assertRaisesRegex(util.OperationError, "404 Not Found"):
            FetchVolume().run(op, Context(op, SimpleNamespace(identity="wvc-test:1:a")))
        self.stg.new_raw_volume.assert_not_called()

    def test_a_name_taken_meanwhile_deletes_nothing(self):
        # another made a volume of that name after the job was queued: libvirt refuses, it stays
        op = self.queue()
        self.stg.new_raw_volume.side_effect = util.OperationError("storage volume 'rocky-10.qcow2' exists already")
        with self.assertRaises(util.OperationError):
            self.run_job(op, [b"ab"])
        op.refresh_from_db()
        self.assertFalse(op.intent["created"])
        self.stg.delete_volume_if_present.assert_not_called()
        FetchVolume().reconcile(op)
        self.stg.delete_volume_if_present.assert_not_called()

    def test_a_size_with_spaces_after_it_is_read(self):
        op = self.queue()
        self.run_job(op, [b"abcd"], size="4 \t")
        self.stg.new_raw_volume.assert_called_once_with("rocky-10.qcow2", 4)

    def test_a_crash_while_libvirt_makes_the_volume_leaves_it_to_recovery(self):
        op = self.queue()
        recorded = []
        self.stg.new_raw_volume.side_effect = lambda name, size: recorded.append(
            Operation.objects.get(pk=op.pk).intent["created"])
        self.run_job(op, [b"ab"])
        self.assertEqual(recorded, [True])

    def test_the_worker_checks_the_name_is_still_free(self):
        op = self.queue()
        self.stg.get_volumes.return_value = ["rocky-10.qcow2"]  # made outside the panel meanwhile
        with self.assertRaisesRegex(util.OperationError, "has a volume named"):
            FetchVolume().precheck(op, None)

    def test_a_deactivated_superuser_s_job_does_not_run(self):
        op = self.queue()
        op.user.is_active = False
        op.user.save()
        op.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            FetchVolume().precheck(op, None)

    def test_the_progress_is_recorded_each_second(self):
        # a slow server: the bar moves before 16 MiB came
        op = self.queue()
        seen = []

        def write(name, size, chunks):
            for _chunk in chunks:
                seen.append(Operation.objects.get(pk=op.pk).intent["done"])
            return size

        self.stg.write_volume.side_effect = write
        clock = iter(range(0, 100, 2))
        with patch("storages.jobs.time.monotonic", side_effect=lambda: next(clock)):
            self.run_job(op, [b"ab", b"cd", b"ef"])
        self.assertEqual(seen, [2, 4, 6])

    def test_more_than_the_size_told_is_not_written(self):
        op = self.queue()
        self.stg.write_volume.side_effect = lambda name, size, chunks: sum(len(c) for c in chunks)
        with self.assertRaisesRegex(util.OperationError, "more than the file's size"):
            self.run_job(op, [b"abcd", b"ef"], size=4)
        self.stg.delete_volume_if_present.assert_called_once_with("rocky-10.qcow2")

    def test_a_cancel_stops_it_and_recovery_deletes_what_it_wrote(self):
        op = self.queue()

        def write(name, size, chunks):
            Operation.objects.filter(pk=op.pk).update(cancel_requested=True)
            return sum(len(c) for c in chunks)

        self.stg.write_volume.side_effect = write
        with self.assertRaises(Cancelled):
            self.run_job(op, [b"x" * 2**20] * 20)
        self.stg.delete_volume_if_present.assert_called_once_with("rocky-10.qcow2")
        # its delete failing: no "cancelled" while the volume may stay; recovery deletes it
        self.stg.delete_volume_if_present.side_effect = OSError("connection lost")
        Operation.objects.filter(pk=op.pk).update(cancel_requested=False)
        with self.assertRaisesRegex(util.OperationError, "was not deleted"):
            self.run_job(op, [b"x" * 2**20] * 20)
        op.refresh_from_db()
        self.assertTrue(op.intent["created"])
        stg = MagicMock()
        with patch("storages.jobs._storage", return_value=(self.compute, stg)):
            self.assertEqual(FetchVolume().reconcile(op).state, Operation.FAILED)
        stg.delete_volume_if_present.assert_called_once_with("rocky-10.qcow2")


class OpenDownloadTestCase(TestCase):
    """The request: redirects followed by hand without reading their bodies, a 200 of an uncompressed body only."""

    def request(self, answers):
        manager = MagicMock()
        manager.request.side_effect = answers
        return patch("storages.jobs.urllib3.PoolManager", return_value=manager), manager

    def test_redirects_are_followed_without_reading_them(self):
        moved = answer([], status=302, headers={"Location": "/mirror/a.iso"})
        final = answer([b"ab"])
        patcher, manager = self.request([moved, final])
        with patcher:
            self.assertIs(open_download("https://images.example.com/a.iso"), final)
        self.assertEqual([c.args[1] for c in manager.request.call_args_list],
                         ["https://images.example.com/a.iso", "https://images.example.com/mirror/a.iso"])
        self.assertEqual(manager.request.call_args.kwargs["headers"], {"Accept-Encoding": "identity"})
        moved.close.assert_called_once_with()
        moved.read.assert_not_called()

    def test_what_is_refused(self):
        for answers, text in (
            ([answer([], status=302, headers={"Location": "file:///etc/passwd"})], "http or https"),
            ([answer([], status=302, headers={"Location": "http://[::1/a.iso"})], "http or https"),
            ([answer([], status=302, headers={"Location": "/again"})] * 7, "redirected more than 5 times"),
            ([answer([], status=206)], "answered 206"),
            ([answer([b"x"], headers={"Content-Encoding": "gzip"})], "not the whole file"),
        ):
            with self.subTest(text=text):
                patcher, _manager = self.request(answers)
                with patcher, self.assertRaisesRegex(util.OperationError, text):
                    open_download("https://images.example.com/a.iso")


class WriteVolumeTestCase(TestCase):
    def test_the_chunks_go_into_a_new_volume_through_one_stream(self):
        stg = wvmStorage.__new__(wvmStorage)
        stg.pool, stg.wvm = MagicMock(), MagicMock()
        stream = stg.wvm.newStream.return_value
        stream.send.side_effect = lambda data: len(data)
        stg.new_raw_volume("a.iso", 4)
        self.assertIn("<name>a.iso</name><capacity unit='bytes'>4</capacity>", stg.pool.createXML.call_args.args[0])
        self.assertEqual(stg.write_volume("a.iso", 4, iter([b"ab", b"cd"])), 4)
        stg.pool.storageVolLookupByName.return_value.upload.assert_called_once_with(stream, 0, 4, 0)
        stream.finish.assert_called_once_with()

    def test_a_failure_aborts_the_stream(self):
        stg = wvmStorage.__new__(wvmStorage)
        stg.pool, stg.wvm = MagicMock(), MagicMock()
        stream = stg.wvm.newStream.return_value

        def chunks():
            yield b"ab"
            raise OSError("connection reset")

        stream.send.side_effect = lambda data: len(data)
        with self.assertRaises(OSError):
            stg.write_volume("a.iso", 4, chunks())
        stream.abort.assert_called_once_with()
        stream.finish.assert_not_called()
