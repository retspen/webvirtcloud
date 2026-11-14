"""A pool a VM needs is not stopped or deleted: stopping one that holds a
running VM's disk would take that disk away, deleting one a VM's definition
names (a disk of type volume) would keep that VM from starting. A disk given
by its file path keeps working without a directory pool's definition, not
without a share's, which mounts it. Runs on a
private libvirt test driver: "test:///default" is shared by the whole process."""

import tempfile
from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

NODE = "<node><pool type='dir'><name>use-pool</name><target><path>/use-pool</path></target></pool></node>"
VOLUME = "<volume><name>v1.img</name><capacity>1048576</capacity></volume>"


def domain(name, disk):
    return (f"<domain type='test'><name>{name}</name><memory>1024</memory><os><type>hvm</type></os>"
            f"<devices><disk device='disk' {disk}<target dev='vda'/></disk></devices></domain>")


class PoolInUseTests(TestCase):
    def setUp(self):
        node = tempfile.NamedTemporaryFile("w", suffix=".xml")
        self.addCleanup(node.close)
        node.write(NODE)
        node.flush()
        self.conn = libvirt.open(f"test://{node.name}")
        self.addCleanup(self.conn.close)
        patcher = patch("vrtManager.connection.connection_manager.get_connection", return_value=self.conn)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pool = self.conn.storagePoolLookupByName("use-pool")
        self.path = self.pool.createXML(VOLUME, 0).path()
        self.compute = Compute.objects.create(name="pool-use", hostname="localhost", login="", password="", type=4)
        self.admin = get_user_model().objects.create_superuser("pool-use", "pu@example.com", "pw")
        self.client.force_login(self.admin)
        self.url = reverse("storage", args=[self.compute.id, "use-pool"])

    def post(self, action):
        response = self.client.post(self.url, {action: ""}, HTTP_REFERER=f"http://testserver{self.url}")
        return [str(m) for m in get_messages(response.wsgi_request)]

    def test_a_pool_that_holds_a_running_vm_disk_is_not_stopped(self):
        self.conn.createXML(domain("disk-user", f"type='file'><source file='{self.path}'/>"), 0)
        messages = self.post("stop")
        self.assertTrue(any(m.startswith("Pool use-pool holds disks of the running VMs disk-user") for m in messages), messages)
        self.assertTrue(self.pool.isActive())
        self.conn.lookupByName("disk-user").destroy()
        self.post("stop")
        self.assertFalse(self.pool.isActive())

    def test_the_api_does_not_stop_it_either(self):
        self.conn.createXML(domain("api-user", f"type='file'><source file='{self.path}'/>"), 0)
        api = APIClient()
        api.force_login(self.admin)
        response = api.post(reverse("compute-storage-stop", kwargs={"compute_pk": self.compute.id, "pk": "use-pool"}))
        self.assertEqual(response.status_code, 400)
        self.assertIn("running VMs api-user", response.json()["detail"])
        self.assertTrue(self.pool.isActive())

    def test_a_pool_a_vm_definition_names_is_not_deleted(self):
        self.conn.defineXML(domain("by-name", "type='volume'><source pool='use-pool' volume='v1.img'/>"))
        self.conn.defineXML(domain("by-path", f"type='file'><source file='{self.path}'/>"))
        self.pool.destroy()
        messages = self.post("delete")
        self.assertTrue(any("by-name" in m and "would no longer start" in m for m in messages), messages)
        self.assertFalse(any("by-path" in m for m in messages), messages)
        self.assertIn("use-pool", self.conn.listDefinedStoragePools())
        self.conn.lookupByName("by-name").undefine()
        self.post("delete")
        self.assertNotIn("use-pool", self.conn.listDefinedStoragePools())

    def test_a_share_a_vm_disk_path_is_in_is_not_deleted(self):
        # undefined, the share is not mounted at the next boot: the path is gone
        self.conn.storagePoolDefineXML(
            "<pool type='netfs'><name>share</name><source><host name='192.0.2.1'/><dir path='/export'/>"
            "<format type='nfs'/></source><target><path>/mnt/share</path></target></pool>", 0)
        self.conn.defineXML(domain("on-share", "type='file'><source file='/mnt/share/v.qcow2'/>"))
        self.conn.defineXML(domain("beside", "type='file'><source file='/mnt/share-2/v.qcow2'/>"))
        url = reverse("storage", args=[self.compute.id, "share"])
        response = self.client.post(url, {"delete": ""})
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertEqual(messages, ["VMs on-share have disks in pool share and would no longer start; detach those disks first"])
        self.conn.lookupByName("on-share").undefine()
        self.client.post(url, {"delete": ""})
        self.assertNotIn("share", self.conn.listDefinedStoragePools())

    def test_an_lvm_pool_counts_its_device_mapper_names_and_iscsi_pools_do_not_share_their_directory(self):
        self.conn.storagePoolDefineXML(
            "<pool type='logical'><name>lvm</name><source><name>vg-data</name><format type='lvm2'/></source>"
            "<target><path>/dev/vg-data</path></target></pool>", 0)
        self.conn.storagePoolDefineXML(
            "<pool type='iscsi'><name>lun</name><source><host name='192.0.2.1'/><device path='iqn.2026-01.test:a'/>"
            "</source><target><path>/dev/disk/by-path</path></target></pool>", 0)
        self.conn.defineXML(domain("on-lv", "type='block'><source dev='/dev/mapper/vg--data-lv1'/>"))
        # another iSCSI pool's LUN: every iSCSI pool's target is /dev/disk/by-path
        self.conn.defineXML(domain("other-lun", "type='block'><source dev='/dev/disk/by-path/ip-192.0.2.9-lun-0'/>"))
        self.client.post(reverse("storage", args=[self.compute.id, "lvm"]), {"delete": ""})
        self.client.post(reverse("storage", args=[self.compute.id, "lun"]), {"delete": ""})
        self.assertIn("lvm", self.conn.listDefinedStoragePools())
        self.assertNotIn("lun", self.conn.listDefinedStoragePools())

    def test_an_inaccessible_pool_has_its_state(self):
        # libvirt's state 4: running, but its storage cannot be reached
        from vrtManager.storage import wvmStorage

        storage = wvmStorage.__new__(wvmStorage)
        for state, status in ((2, "Running normally"), (4, "Inaccessible"), (9, "Unknown")):
            with self.subTest(state=state):
                storage.pool = type("Pool", (), {"info": lambda self, state=state: [state, 0, 0, 0]})()
                self.assertEqual(storage.get_status(), status)
