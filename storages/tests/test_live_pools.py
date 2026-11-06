"""Live check that a directory or NFS pool created on the storages page
starts when its directory does not exist yet: libvirt builds it. Runs only
with TEST_LIBVIRT_HOST set; the NFS case needs TEST_LIBVIRT_NFS_EXPORT, a
directory the host exports to its 127.0.0.1 (the Vagrant computes do)."""

import os
import unittest

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from vrtManager.tests import livetest
from vrtManager.connection import connection_manager

P = livetest.PREFIX


@unittest.skipUnless(livetest.enabled(), "Set TEST_LIBVIRT_HOST to run the live libvirt tests")
class LivePoolsTestCase(TestCase):
    def setUp(self):
        args = dict(
            hostname=os.environ["TEST_LIBVIRT_HOST"],
            login=os.environ.get("TEST_LIBVIRT_LOGIN", ""),
            password=os.environ.get("TEST_LIBVIRT_PASSWORD", ""),
            type=int(os.environ.get("TEST_LIBVIRT_TYPE", 1)),
        )
        self.conn = connection_manager.get_connection(*args.values())
        self.compute = Compute.objects.create(name="live-pools", **args)
        self.client.force_login(get_user_model().objects.create_superuser("live-pools", "lp@example.com", "x"))

    def remove_pool(self, name):
        try:
            pool = self.conn.storagePoolLookupByName(name)
        except libvirt.libvirtError:
            return
        if pool.isActive():
            pool.destroy()  # unmounts an NFS pool
            pool.delete(0)  # removes the directory
        pool.undefine()

    def assert_created(self, data):
        self.remove_pool(data["name"])
        self.addCleanup(self.remove_pool, data["name"])
        response = self.client.post(reverse("storages", args=[self.compute.id]), {"create": "", **data})
        self.assertRedirects(
            response, reverse("storage", args=[self.compute.id, data["name"]]), fetch_redirect_response=False
        )
        pool = self.conn.storagePoolLookupByName(data["name"])
        self.assertTrue(pool.isActive())
        self.assertTrue(pool.autostart())

    def test_a_missing_directory_is_built(self):
        self.assert_created({"name": P + "dir", "stg_type": "dir", "target": f"/var/lib/libvirt/{P}dir"})

    @unittest.skipUnless(os.environ.get("TEST_LIBVIRT_NFS_EXPORT"), "Set TEST_LIBVIRT_NFS_EXPORT to run the NFS pool test")
    def test_a_missing_mount_point_is_built(self):
        self.assert_created({
            "name": P + "nfs",
            "stg_type": "netfs",
            "netfs_host": "127.0.0.1",
            "source": os.environ["TEST_LIBVIRT_NFS_EXPORT"],
            "source_format": "nfs",
            "target": f"/var/lib/libvirt/{P}nfs",
        })
