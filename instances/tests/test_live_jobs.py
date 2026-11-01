"""Live checks for the instance jobs: the worker runs them against libvirt
and recovery reads the same outcome back. Runs only with TEST_LIBVIRT_HOST
set (see instances/tests/livetest.py). The migration needs a second host:
TEST_LIBVIRT_SSH_HOST (and _LOGIN), with TEST_LIBVIRT_MIGRATE_ADDRESS as its
migration address. The ISO upload runs on both hosts: TCP writes through a
libvirt stream, SSH through SFTP."""

import os
import subprocess
import time
import unittest

import libvirt
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase
from django.urls import reverse
from vrtManager.connection import connection_manager, wvmConnect
from vrtManager.instance import wvmInstance

from appsettings.settings import get_settings
from computes.models import Compute
from instances.jobs import DeleteExternalSnapshot
from instances.models import Instance
from operations import jobs
from operations.models import Operation
from operations.tests import fakes
from operations.worker import Worker

from . import livetest

P = livetest.PREFIX


def wait_for(predicate, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.5)
    return False


class LiveJobsTestCase(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        if not livetest.enabled():
            raise unittest.SkipTest("Set TEST_LIBVIRT_HOST to run the live libvirt tests")
        cls.args = (
            os.environ["TEST_LIBVIRT_HOST"],
            os.environ.get("TEST_LIBVIRT_LOGIN", ""),
            os.environ.get("TEST_LIBVIRT_PASSWORD", ""),
            int(os.environ.get("TEST_LIBVIRT_TYPE", 4)),
        )
        cls.conn = connection_manager.get_connection(*cls.args)
        livetest.cleanup(cls.conn)
        livetest.ensure_pool(cls.conn)
        cls.inventory = livetest.inventory(cls.conn)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        try:
            livetest.remove_pool(cls.conn)
        finally:
            super().tearDownClass()
        if livetest.inventory(cls.conn) != cls.inventory:
            raise AssertionError("Live tests changed objects outside the test namespace")

    def setUp(self):
        get_settings()
        host, login, password, conn_type = self.args
        self.compute = Compute.objects.create(name=P + "compute", hostname=host, login=login, password=password,
                                              type=conn_type)
        self.admin = get_user_model().objects.create_superuser("job_live_admin", "a@example.com", "pw")

    def tearDown(self):
        livetest.cleanup(self.conn)

    def vm(self, name, state="stopped"):
        base = livetest.create_volume(self.conn, P + name)
        dom = livetest.define_vm(self.conn, P + name, [base])
        if state == "running":
            dom.create()
        return dom, wvmInstance(*self.args, None, uuid=dom.UUIDString())

    def test_the_worker_deletes_a_snapshot_and_recovery_agrees(self):
        dom, vm = self.vm("job-del", "running")
        vm.create_external_snapshot("one")
        instance = Instance.objects.create(compute=self.compute, name=dom.name(), uuid=dom.UUIDString())
        op = jobs.submit("snapshot.delete", self.admin, {"instance": instance.pk, "name": "one"}, "key-live0001")
        worker = Worker(concurrency=1, tick=0.1, heartbeat_every=1, progress_every=1, exit_on_lost_lease=False)
        thread = fakes.start_worker(worker)
        try:
            self.assertTrue(wait_for(lambda: Operation.objects.get(pk=op.pk).state == Operation.SUCCEEDED, 180))
        finally:
            fakes.stop_worker(worker, thread)
        self.assertEqual(dom.snapshotNum(0), 0)
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING)
        op.refresh_from_db()
        self.assertEqual(DeleteExternalSnapshot().reconcile(op).state, Operation.SUCCEEDED)

    def run_job(self, op):
        worker = Worker(concurrency=1, tick=0.1, heartbeat_every=1, progress_every=1, exit_on_lost_lease=False)
        thread = fakes.start_worker(worker)
        try:
            self.assertTrue(wait_for(lambda: Operation.objects.get(pk=op.pk).state in Operation.TERMINAL, 300))
        finally:
            fakes.stop_worker(worker, thread)
        op.refresh_from_db()
        self.assertEqual(op.state, Operation.SUCCEEDED, op.error)
        return op

    def test_snapshot_create_and_revert_run_as_jobs(self):
        running, _vm = self.vm("smoke-ext", "running")
        stopped, _vm = self.vm("smoke-int")
        steps = ((running, "snapshot.create", {"name": "m", "external": True, "memory": True}),
                 (running, "snapshot.create", {"name": "d", "external": True}),
                 (running, "snapshot.revert", {"name": "m", "external": True}),
                 (stopped, "snapshot.create", {"name": "i"}),
                 (stopped, "snapshot.revert", {"name": "i"}))
        for n, (dom, kind, params) in enumerate(steps):
            instance = Instance.objects.get_or_create(compute=self.compute, name=dom.name(), uuid=dom.UUIDString())[0]
            self.run_job(jobs.submit(kind, self.admin, {"instance": instance.pk, **params}, f"key-snap{n:04d}"))
        self.assertEqual(running.snapshotCurrent(0).getName(), "m")
        self.assertTrue(running.isActive())  # a memory snapshot resumes the VM
        self.assertEqual(stopped.snapshotCurrent(0).getName(), "i")

    def test_clone_create_and_volume_clone_run_as_jobs(self):
        dom, _vm = self.vm("smoke-src")
        source = Instance.objects.create(compute=self.compute, name=dom.name(), uuid=dom.UUIDString())
        op = self.run_job(jobs.submit("instance.clone", self.admin, {
            "instance": source.pk, "name": P + "smoke-clone", "disk-vda": P + "smoke-clone.qcow2",
            "clone-net-mac-0": "52:54:00:00:31:01"}, "key-smoke001"))
        self.assertEqual(self.conn.lookupByUUIDString(op.intent["uuid"]).name(), P + "smoke-clone")
        self.run_job(jobs.submit("volume.clone", self.admin, {
            "compute": self.compute.pk, "pool": livetest.POOL, "image": P + "smoke-src.qcow2",
            "name": P + "smoke-copy"}, "key-smoke002"))
        self.assertTrue(livetest.volume_exists(self.conn, f"{livetest.POOL_PATH}/{P}smoke-copy.qcow2"))
        op = self.run_job(jobs.submit("instance.create", self.admin, {
            "name": P + "smoke-new", "firmware": "BIOS", "vcpu": 1, "vcpu_mode": "host-model", "memory": 256,
            "networks": "default", "storage": livetest.POOL, "template": P + "smoke-copy.qcow2", "images": "",
            "hdd_size": 0, "cache_mode": "none", "meta_prealloc": False, "virtio": True, "qemu_ga": False,
            "mac": "", "nwfilter": "", "net_model": "virtio", "add_cdrom": "None", "add_input": "default",
            "video": "vga", "listener_addr": "127.0.0.1", "compute": self.compute.pk, "arch": "x86_64",
            "machine": "q35"}, "key-smoke003"))
        self.assertEqual(self.conn.lookupByUUIDString(op.intent["uuid"]).name(), P + "smoke-new")

    def second_host(self):
        if not os.environ.get("TEST_LIBVIRT_SSH_HOST"):
            self.skipTest("Set TEST_LIBVIRT_SSH_HOST to a second host to run the live migration test")
        dest = Compute.objects.create(name=P + "dest", hostname=os.environ["TEST_LIBVIRT_SSH_HOST"],
                                      login=os.environ.get("TEST_LIBVIRT_SSH_LOGIN", "root"), password="", type=2,
                                      migration_address=os.environ.get("TEST_LIBVIRT_MIGRATE_ADDRESS", ""))
        dest_conn = connection_manager.get_connection(dest.hostname, dest.login, "", 2)
        dest_inventory = livetest.inventory(dest_conn)
        self.addCleanup(lambda: self.assertEqual(livetest.inventory(dest_conn), dest_inventory))
        self.addCleanup(livetest.cleanup, dest_conn)
        return dest, dest_conn

    def test_a_migration_runs_as_a_job_there_and_back(self):
        dest, dest_conn = self.second_host()
        dom = livetest.define_vm(self.conn, P + "migrate", [])
        dom.create()
        uuid = dom.UUIDString()
        instance = Instance.objects.create(compute=self.compute, name=dom.name(), uuid=uuid)
        live = {"instance": instance.pk, "target": dest.pk, "live": True, "autoconverge": True}
        self.run_job(jobs.submit("instance.migrate", self.admin, live, "key-mig00001"))
        self.assertTrue(dest_conn.lookupByUUIDString(uuid).isActive())
        dest_conn.lookupByUUIDString(uuid).destroy()
        offline = {"instance": instance.pk, "target": self.compute.pk, "offline": True}
        self.run_job(jobs.submit("instance.migrate", self.admin, offline, "key-mig00002"))
        self.assertFalse(self.conn.lookupByUUIDString(uuid).isActive())  # defined on the source again
        self.assertEqual(Instance.objects.get(uuid=uuid).compute, self.compute)

    def test_a_disk_neither_host_shares_is_copied_there_and_back(self):
        """The test pool is a directory of each host's own: the disk is
        copied into it, running there with its source file deleted on
        request, shut off back (started paused for the copy) with it kept."""
        dest, dest_conn = self.second_host()
        self.addCleanup(livetest.remove_pool, dest_conn)
        livetest.ensure_pool(dest_conn)
        path = livetest.create_volume(self.conn, P + "copy")
        dom = livetest.define_vm(self.conn, P + "copy", [path])
        dom.create()
        uuid = dom.UUIDString()
        instance = Instance.objects.create(compute=self.compute, name=dom.name(), uuid=uuid)
        pools = {"vda": livetest.POOL}
        there = {"instance": instance.pk, "target": dest.pk, "live": True, "disk_pools": pools, "delete_source": True}
        self.run_job(jobs.submit("instance.migrate", self.admin, there, "key-copy0001"))
        self.assertTrue(dest_conn.lookupByUUIDString(uuid).isActive())
        self.assertEqual((livetest.volume_exists(self.conn, path), livetest.volume_exists(dest_conn, path)),
                         (False, True))
        dest_conn.lookupByUUIDString(uuid).destroy()
        back = {"instance": instance.pk, "target": self.compute.pk, "offline": True, "disk_pools": pools}
        self.run_job(jobs.submit("instance.migrate", self.admin, back, "key-copy0002"))
        self.assertFalse(self.conn.lookupByUUIDString(uuid).isActive())
        self.assertEqual((livetest.volume_exists(self.conn, path), livetest.volume_exists(dest_conn, path)),
                         (True, True))

    def test_a_disk_moves_to_another_pool_and_back(self):
        """There while the VM runs (block copy and pivot), back shut off
        (volume copy); each time the source file goes."""
        other = self.conn.storagePoolDefineXML(
            f"<pool type='dir'><name>{P}move</name><target><path>{livetest.POOL_PATH}-move</path></target></pool>")
        other.create(libvirt.VIR_STORAGE_POOL_CREATE_WITH_BUILD)

        def remove_other():
            other.refresh(0)
            for vol in other.listAllVolumes():
                vol.delete(0)
            other.destroy()
            other.delete(0)
            other.undefine()
        self.addCleanup(remove_other)
        path = livetest.create_volume(self.conn, P + "move")
        dom = livetest.define_vm(self.conn, P + "move", [path])
        dom.create()
        instance = Instance.objects.create(compute=self.compute, name=dom.name(), uuid=dom.UUIDString())
        moved = f"{livetest.POOL_PATH}-move/{P}move.qcow2"

        def source(flags):
            return dom.XMLDesc(flags).split("<source file='")[1].split("'")[0]

        self.run_job(jobs.submit("disk.move", self.admin, {"instance": instance.pk, "dev": "vda", "pool": P + "move"},
                                 "key-move0001"))
        self.assertEqual((source(0), source(libvirt.VIR_DOMAIN_XML_INACTIVE)), (moved, moved))
        self.assertFalse(livetest.volume_exists(self.conn, path))  # no host uses the source file: it went
        dom.destroy()
        self.run_job(jobs.submit("disk.move", self.admin, {"instance": instance.pk, "dev": "vda", "pool": livetest.POOL},
                                 "key-move0002"))
        self.assertEqual(source(libvirt.VIR_DOMAIN_XML_INACTIVE), path)

    def test_a_shut_off_uefi_vm_migrates_with_its_nvram_there_and_back(self):
        dest, _dest_conn = self.second_host()
        hosts = {self.compute.pk: wvmConnect(*self.args), dest.pk: wvmConnect(dest.hostname, dest.login, "", 2)}
        dom = livetest.define_vm(self.conn, P + "uefi", [], uefi=True)
        dom.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)  # libvirt makes the NVRAM file
        dom.destroy()
        name = os.path.basename(wvmInstance(*self.args, None, uuid=dom.UUIDString()).get_nvram())

        def nvram(compute):
            host = hosts[compute.pk]
            with host._nvram_pool() as pool:
                vol = host._find_volume(pool, name)
                if vol is None:
                    return None
                stream, chunks = host.wvm.newStream(0), []
                vol.download(stream, 0, 0, 0)
                stream.recvAll(lambda _stream, data, out: out.append(data), chunks)
                stream.finish()
                return b"".join(chunks)

        content = nvram(self.compute)
        instance = Instance.objects.create(compute=self.compute, name=dom.name(), uuid=dom.UUIDString())
        for n, (source, target) in enumerate(((self.compute, dest), (dest, self.compute))):
            offline = {"instance": instance.pk, "target": target.pk, "offline": True}
            self.run_job(jobs.submit("instance.migrate", self.admin, offline, f"key-uefi{n:04d}"))
            self.assertEqual(nvram(target), content)
            self.assertIsNone(nvram(source))

    def test_a_shut_off_vm_with_tpm_state_migrates_with_it_there_and_back(self):
        dest, dest_conn = self.second_host()
        tpm = "<tpm model='tpm-crb'><backend type='emulator' version='2.0'/></tpm>"
        # UEFI with a TPM, as a Windows 11 VM: its NVRAM file is copied, its TPM state migrated
        dom = livetest.define_vm(self.conn, P + "tpm", [], uefi=True, extra_devices=tpm)
        dom.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)  # swtpm makes the state
        dom.destroy()
        uuid = dom.UUIDString()

        def state_on_dest():
            """The checksum of the TPM state file on the destination (an SSH host, as root)."""
            path = f"/var/lib/libvirt/swtpm/{uuid}/tpm2/tpm2-00.permall"
            return subprocess.run(["ssh", "-o", "BatchMode=yes", "-l", dest.login, dest.hostname,
                                   f"sha256sum {path} 2>/dev/null"], capture_output=True, text=True).stdout.split()[:1]

        instance = Instance.objects.create(compute=self.compute, name=dom.name(), uuid=uuid)
        sums = []
        for n, target in enumerate((dest, self.compute, dest)):
            offline = {"instance": instance.pk, "target": target.pk, "offline": True}
            self.run_job(jobs.submit("instance.migrate", self.admin, offline, f"key-tpm{n:05d}"))
            sums.append(state_on_dest())
        self.assertFalse(dest_conn.lookupByUUIDString(uuid).isActive())  # shut off again after the move
        # the same state went there, back and there again; none stays behind
        self.assertTrue(sums[0])
        self.assertEqual((sums[1], sums[2]), ([], sums[0]))

    def upload(self, compute, key, chunks):
        """Post chunks of a two-chunk ISO upload to the storage view; returns the job."""
        self.client.force_login(self.admin)
        url = reverse("storage", args=[compute.pk, livetest.POOL])
        name = P + "upload.iso"
        for index in chunks:
            answer = self.client.post(url, {
                "iso_upload": "1", "file": SimpleUploadedFile(name, b"%d" % index * 4096), "file_name": name,
                "chunk_index": str(index), "total_chunks": "2", "file_size": str(2 * 4096), "upload_id": key})
            self.assertEqual(answer.status_code, 200, answer.content)
        return Operation.objects.get(pk=answer.json()["job"])

    def pool_volumes(self, conn):
        pool = conn.storagePoolLookupByName(livetest.POOL)
        pool.refresh(0)
        return set(pool.listVolumes())

    def test_an_iso_upload_runs_as_a_job(self):
        hosts = [(self.compute, self.conn)]
        if os.environ.get("TEST_LIBVIRT_SSH_HOST"):
            ssh = Compute.objects.create(name=P + "ssh", hostname=os.environ["TEST_LIBVIRT_SSH_HOST"],
                                         login=os.environ.get("TEST_LIBVIRT_SSH_LOGIN", "root"), password="", type=2)
            ssh_conn = connection_manager.get_connection(ssh.hostname, ssh.login, "", 2)
            ssh_inventory = livetest.inventory(ssh_conn)
            self.addCleanup(lambda: self.assertEqual(livetest.inventory(ssh_conn), ssh_inventory))
            self.addCleanup(livetest.remove_pool, ssh_conn)
            livetest.ensure_pool(ssh_conn)
            hosts.append((ssh, ssh_conn))
        for n, (compute, conn) in enumerate(hosts):
            with self.subTest(host=compute.name):
                op = self.upload(compute, f"live-upload-{n}", (0, 1))
                self.assertEqual(op.state, Operation.SUCCEEDED, op.error)
                self.assertEqual(self.pool_volumes(conn), {P + "upload.iso"})
                conn.storagePoolLookupByName(livetest.POOL).storageVolLookupByName(P + "upload.iso").delete(0)
                op = self.upload(compute, f"live-cancel-{n}", (0,))
                self.assertTrue(self.pool_volumes(conn))  # the volume, or the SSH part file
                self.assertEqual(jobs.cancel(op.pk, self.admin).state, Operation.CANCELLED)
                self.assertEqual(self.pool_volumes(conn), set())
