"""backup.import: a target's manifests read into the panel, each checked as
a restore checks it."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import libvirt
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse

from appsettings.settings import get_settings
from computes.models import Compute
from instances.models import Instance
from operations import jobs
from operations.jobs import Context
from operations.models import Operation, acquire
from vmbackups.jobs import ImportBackups
from vmbackups.models import Backup, BackupTarget, BackupTargetPool

GIB = 1024**3
WORKER = "wvc-test:1:a"
DOMAIN = b"<domain><name>vm1</name></domain>"


def manifest(uuid, vm_uuid="51515151-0000-4000-8000-000000000001"):
    return {
        "format": 1, "backup": uuid, "vm": {"name": "vm1", "uuid": vm_uuid}, "compute": "h0",
        "created_at": "2026-11-01T10:00:00+00:00", "consistency": "frozen", "nvram": "none", "left_out": [],
        "libvirt": 11010000, "hypervisor": 10001000,
        "files": [
            {"role": "disk", "dev": "vda", "volume": f"wvc-{uuid}-vda.qcow2", "format": "qcow2", "capacity": GIB,
             "size": GIB // 2, "sha256": ""},
            {"role": "domain", "dev": "", "volume": f"wvc-{uuid}-domain.xml", "format": "", "capacity": len(DOMAIN),
             "size": len(DOMAIN), "sha256": hashlib.sha256(DOMAIN).hexdigest()},
        ],
    }


def error(code):
    err = libvirt.libvirtError("x")
    err.err = (code,)
    return err


class ImportTests(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.admin = get_user_model().objects.create_superuser("im_admin", "a@example.com", "pw")
        self.compute = Compute.objects.create(name="h1", hostname="192.0.2.51", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=self.compute, name="vm1", uuid="51515151-0000-4000-8000-000000000001")
        self.target = BackupTarget.objects.create(name="nfs1")
        BackupTargetPool.objects.create(target=self.target, compute=self.compute, pool="b1", pool_uuid="u")
        self.a, self.b = str(uuid4()), str(uuid4())
        self.files = {}
        for uuid in (self.a, self.b):
            self.files[f"wvc-{uuid}-manifest.json"] = json.dumps(manifest(uuid)).encode()
            self.files[f"wvc-{uuid}-domain.xml"] = DOMAIN
            self.files[f"wvc-{uuid}-vda.qcow2"] = None
        self.pool = MagicMock()

        def volume(name):
            if name not in self.files:
                raise error(libvirt.VIR_ERR_NO_STORAGE_VOL)
            vol = MagicMock()
            vol.info.return_value = [0, GIB, GIB // 2]
            return vol

        self.pool.storageVolLookupByName.side_effect = volume
        for name, value in (
            ("vmbackups.jobs.wvmConnect", MagicMock()),
            ("vmbackups.jobs.target_pool", MagicMock(return_value=self.pool)),
            ("vmbackups.jobs.manifest_names", MagicMock(side_effect=lambda pool: sorted(
                n for n in self.files if n.endswith("-manifest.json")))),
            ("vmbackups.jobs.get_file", MagicMock(side_effect=lambda conn, pool, name: self.files[name])),
        ):
            patcher = patch(name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def read(self):
        op = jobs.submit("backup.import", self.admin, {"target": self.target.pk}, f"key-{uuid4().hex[:12]}")
        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        result = ImportBackups().run(op, Context(op, SimpleNamespace(identity=WORKER)))
        jobs.finish(op, jobs.Outcome(Operation.SUCCEEDED, result=result))
        return result

    def test_new_manifests_are_added_once(self):
        self.assertEqual(self.read(), {"added": 2})
        backup = Backup.objects.get(uuid=self.a)
        self.assertEqual((backup.state, backup.target, backup.instance, backup.vm_name, backup.consistency),
                         (Backup.READY, self.target, self.vm, "vm1", "frozen"))
        self.assertEqual(backup.created_at.isoformat(), "2026-11-01T10:00:00+00:00")
        self.assertEqual(sorted(backup.files.values_list("role", flat=True)), ["disk", "domain"])
        self.assertEqual(self.read(), {"added": 0})
        self.assertEqual(Backup.objects.count(), 2)

    def test_a_manifest_with_a_missing_file_is_incomplete(self):
        del self.files[f"wvc-{self.b}-vda.qcow2"]
        self.files[f"wvc-{self.a}-domain.xml"] = b"<domain/>"  # changed since it was written
        result = self.read()
        self.assertEqual(result["added"], 0)
        # the job page shows a warning
        self.assertEqual(result["warning"][0]["values"]["names"],
                         ", ".join(sorted([f"wvc-{self.a}-manifest.json", f"wvc-{self.b}-manifest.json"])))
        self.assertFalse(Backup.objects.exists())

    def test_a_damaged_manifest_is_passed_over(self):
        self.files[f"wvc-{self.a}-manifest.json"] = b'{"format": 1, "backup'  # cut short as it was written
        result = self.read()
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["warning"][0]["values"]["names"], f"wvc-{self.a}-manifest.json")
        self.assertTrue(Backup.objects.filter(uuid=self.b).exists())

    def test_a_manifest_of_another_format_or_without_its_fields_is_passed_over(self):
        other = manifest(self.a)
        other["format"] = 2
        self.files[f"wvc-{self.a}-manifest.json"] = json.dumps(other).encode()
        broken = manifest(self.b)
        broken["created_at"] = "yesterday"  # parse_datetime gives None
        self.files[f"wvc-{self.b}-manifest.json"] = json.dumps(broken).encode()
        result = self.read()
        self.assertEqual(result["added"], 0)
        self.assertIn(f"wvc-{self.b}-manifest.json", result["warning"][0]["values"]["names"])
        self.assertIn(f"wvc-{self.a}-manifest.json", result["warning"][0]["values"]["names"])

    def test_a_known_backup_is_left_alone(self):
        Backup.objects.create(uuid=self.a, target=self.target, vm_uuid="x", vm_name="kept", compute_name="h1",
                              state=Backup.READY)
        self.assertEqual(self.read()["added"], 1)
        self.assertEqual(Backup.objects.get(uuid=self.a).vm_name, "kept")

    def test_a_backup_of_a_removed_vm_has_no_vm(self):
        self.vm.delete()
        self.read()
        self.assertIsNone(Backup.objects.get(uuid=self.a).instance)

    def test_the_target_page_reads_the_target(self):
        self.client.force_login(self.admin)
        url = reverse("vmbackups:target", args=[self.target.pk])
        with patch("vmbackups.views.wvmConnect"), patch("vmbackups.views.target_pool") as page_pool, \
                patch("vmbackups.views.inside_vm_pool", return_value=None):
            page_pool.return_value.info.return_value = [2, 100 * GIB, 40 * GIB, 60 * GIB]
            self.assertContains(self.client.get(url), 'name="import"')
        response = self.client.post(url, {"import": "1", "submission_key": "key-page-imp1"})
        op = Operation.objects.get()
        self.assertEqual(op.kind, "backup.import")
        self.assertRedirects(response, reverse("operations:job", args=[op.pk]), fetch_redirect_response=False)
