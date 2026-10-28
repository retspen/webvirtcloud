"""The storage pool target and source checks run in linear time and take
paths of letters, digits and "/", "_", ".", ":" and "-" (not first, not right
after "/"): both values go into the pool XML."""

import time
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from lxml import html
from storages.forms import AddStgPool


def target_error(target):
    form = AddStgPool({"name": "pool1", "stg_type": "dir", "target": target})
    form.is_valid()
    return "target" in form.errors


def source_error(source, stg_type="logical"):
    form = AddStgPool({"name": "pool1", "stg_type": stg_type, "source": source, "target": "/mnt/pool1"})
    form.is_valid()
    return "source" in form.errors


class PoolTargetTests(SimpleTestCase):
    def test_accepted_and_refused_targets(self):
        for target, refused in (
            ("/var/lib/libvirt/images", False),
            ("/srv/iso-pool", False),
            ("/a//b", False),
            ("a-b.c_d/e", False),
            ("/a/-b", True),  # a dash right after a slash
            ("-x", True),
            ("/a b", True),
            ("'/a", True),  # any first character but "-" passed
            ("</a", True),
        ):
            with self.subTest(target=target):
                self.assertEqual(target_error(target), refused)

    def test_accepted_and_refused_sources(self):
        for source, refused in (
            ("/dev/vdb", False),
            ("/dev/mapper/vg0-data", False),
            ("/dev/disk/by-id/wwn-0x5000c500a1b2c3d4", False),
            ("/dev/disk/by-path/pci-0000:00:1f.2-ata-1", False),
            ("/export/vm_images.v2", False),
            ("", True),
            ("-x", True),  # would read as an option
            ("/a/-b", True),
            ("/a b", True),
            ("/a'b", True),  # the value goes into the pool XML
            ("/a<b", True),
            ("'/a", True),
        ):
            for stg_type in ("logical", "netfs"):
                with self.subTest(source=source, stg_type=stg_type):
                    self.assertEqual(source_error(source, stg_type), refused)

    def test_a_crafted_target_is_checked_at_once(self):
        # the previous expression backtracked exponentially: 22 dashes took over a second
        start = time.monotonic()
        self.assertTrue(target_error("," + "-" * 98 + "!"))
        self.assertLess(time.monotonic() - start, 1)

    def test_the_create_form_leaves_the_path_check_to_the_server(self):
        # a stricter pattern or a shorter maxlength in the page refuses paths the form accepts
        superuser = SimpleNamespace(user=SimpleNamespace(is_superuser=True))
        ceph = [{"uuid": "00000000-0000-0000-0000-000000000001", "usage": "client.libvirt"}]
        page = html.fromstring(render_to_string("create_stg_block.html", {"request": superuser, "ceph_secrets": ceph}))
        fields = page.xpath("//input[@name='target' or @name='source']")
        self.assertEqual(len(fields), 5)  # directory, LVM device, share, its mount point, ISO directory
        for field in fields:
            with self.subTest(id=field.get("id")):
                self.assertIsNone(field.get("pattern"))
                self.assertGreaterEqual(int(field.get("maxlength", 100)), 100)
        for name in ("netfs_host", "ceph_host"):  # a host name is up to 253 characters
            with self.subTest(name=name):
                self.assertGreaterEqual(int(page.xpath(f"//input[@name='{name}']/@maxlength")[0]), 253)
