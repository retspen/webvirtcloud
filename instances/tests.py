import re

from accounts.models import UserAttributes, UserInstance, UserSSHKey
from appsettings.models import AppSettings
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.http.response import Http404
from django.shortcuts import reverse
from django.test import TestCase
from instances.views import instance
from libvirt import VIR_DOMAIN_UNDEFINE_NVRAM
from vrtManager.create import wvmCreate
from vrtManager.util import randomUUID

from .models import Flavor, Instance
from .utils import refr


class InstancesTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Add users for testing purposes
        User = get_user_model()
        cls.admin_user = User.objects.get(pk=1)
        cls.test_user = User.objects.create(username="test-user")
        UserAttributes.objects.create(
            user=cls.test_user,
            max_instances=1,
            max_cpus=1,
            max_memory=128,
            max_disk_size=1,
        )
        permission = Permission.objects.get(codename="clone_instances")
        cls.test_user.user_permissions.add(permission)

        # Add localhost compute
        cls.compute = Compute(
            name="test-compute",
            hostname="localhost",
            login="",
            password="",
            details="local",
            type=4,
        )
        cls.compute.save()

        cls.connection = wvmCreate(
            cls.compute.hostname,
            cls.compute.login,
            cls.compute.password,
            cls.compute.type,
        )

        # Add disks for testing
        cls.connection.create_volume(
            "default",
            "test-volume",
            1,
            "qcow2",
            False,
            0,
            0,
        )
        # XML for testing vm
        with open("conf/test-vm.xml", "r") as f:
            cls.xml = f.read()

        # Create testing vm from XML
        cls.connection._defineXML(cls.xml)
        refr(cls.compute)
        cls.instance: Instance = Instance.objects.get(pk=1)

    @classmethod
    def tearDownClass(cls):
        # Destroy testing vm
        cls.instance.proxy.delete_all_disks()
        cls.instance.proxy.delete(VIR_DOMAIN_UNDEFINE_NVRAM)
        super().tearDownClass()

    def setUp(self):
        self.client.login(username="admin", password="admin")
        self.rsa_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQC6OOdbfv27QVnSC6sKxGaHb6YFc+3gxCkyVR3cTSXE/n5BEGf8aOgBpepULWa1RZfxYHY14PlKULDygdXSdrrR2kNSwoKz/Oo4d+3EE92L7ocl1+djZbptzgWgtw1OseLwbFik+iKlIdqPsH+IUQvX7yV545ZQtAP8Qj1R+uCqkw== test@test"

    def test_index(self):
        response = self.client.get(reverse("instances:index"))
        self.assertEqual(response.status_code, 200)

        self.client.force_login(self.test_user)
        response = self.client.get(reverse("instances:index"))
        self.assertEqual(response.status_code, 200)

    def test_create_select_type(self):
        response = self.client.get(
            reverse("instances:create_instance_select_type", args=[1])
        )
        self.assertEqual(response.status_code, 200)

    def test_instance_page(self):
        response = self.client.get(
            reverse("instances:instance", args=[self.instance.id])
        )
        self.assertEqual(response.status_code, 200)

        self.client.force_login(self.test_user)
        response = self.client.get(
            reverse("instances:instance", args=[self.instance.id])
        )
        self.assertRaises(Http404)

    # def test_create_volume(self):
    #     response = self.client.post(
    #         reverse('create_volume', args=[self.compute.id, 'default']),
    #         {
    #             'name': 'test',
    #             'format': 'qcow2',
    #             'size': '1',
    #             'meta_prealloc': False,
    #         },
    #     )
    #     self.assertRedirects(response, reverse('storage', args=[self.compute.id, 'default']))

    def test_create_destroy_instance(self):
        # Create
        response = self.client.get(
            reverse(
                "instances:create_instance", args=[self.compute.id, "x86_64", "q35"]
            )
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse(
                "instances:create_instance", args=[self.compute.id, "x86_64", "q35"]
            ),
            {
                "name": "test",
                "firmware": "BIOS",
                "vcpu": 1,
                "vcpu_mode": "host-model",
                "memory": 128,
                "device0": "disk",
                "bus0": "virtio",
                "images": "test-volume.qcow2",
                "storage-control": "default",
                "image-control": "test.qcow2",
                "networks": "default",
                "network-control": "default",
                "cache_mode": "directsync",
                "nwfilter": "",
                "graphics": "spice",
                "video": "vga",
                "listener_addr": "0.0.0.0",
                "console_pass": "",
                "qemu_ga": False,
                "virtio": True,
                "create": True,
            },
        )
        self.assertEqual(response.status_code, 302)

        instance_qs: Instance = Instance.objects.filter(name="test")
        self.assertEqual(len(instance_qs), 1)

        instance = instance_qs[0]

        # Destroy
        response = self.client.get(reverse("instances:destroy", args=[instance.id]))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("instances:destroy", args=[instance.id]),
            {},  # do not destroy disk image
            HTTP_REFERER=reverse("index"),
        )
        self.assertRedirects(response, reverse("instances:index"))

    def test_create_from_xml(self):
        uuid = randomUUID()
        xml = self.xml.replace("test-vm", "test-vm-xml")
        xml = re.sub("\s?<uuid>.*?</uuid>", f"<uuid>{uuid}</uuid>", xml)
        response = self.client.post(
            reverse("instances:create_instance_select_type", args=[self.compute.id]),
            {
                "create_xml": True,
                "dom_xml": xml,
            },
        )
        self.assertEqual(response.status_code, 302)

        xml_instance_qs: Instance = Instance.objects.filter(name="test-vm-xml")
        self.assertEqual(len(xml_instance_qs), 1)

        xml_instance = xml_instance_qs[0]

        # destroy started instance to maximize coverage
        xml_instance.proxy.start()

        response = self.client.post(
            reverse("instances:destroy", args=[xml_instance.id]),
            {},  # do not delete disk image
            HTTP_REFERER=reverse("index"),
        )
        self.assertRedirects(response, reverse("instances:index"))

    def test_resize_cpu(self):
        self.assertEqual(self.instance.vcpu, 1)
        self.assertEqual(self.instance.cur_vcpu, 1)

        response = self.client.post(
            reverse("instances:resizevm_cpu", args=[self.instance.id]),
            {
                "vcpu": 4,
                "cur_vcpu": 2,
            },
        )
        self.assertRedirects(
            response, reverse("instances:instance", args=[self.instance.id]) + "#resize"
        )

        # reset cached properties
        del self.instance.vcpu
        del self.instance.cur_vcpu

        self.assertEqual(self.instance.vcpu, 4)
        self.assertEqual(self.instance.cur_vcpu, 2)

    def test_resize_cpu_with_quota(self):
        # test for non admin user with quotas
        vcpu = self.instance.vcpu
        cur_vcpu = self.instance.cur_vcpu

        UserInstance.objects.create(
            user=self.test_user, instance=self.instance, is_change=True
        )

        self.client.force_login(self.test_user)

        response = self.client.post(
            reverse("instances:resizevm_cpu", args=[self.instance.id]),
            {
                "vcpu": 4,
                "cur_vcpu": 2,
            },
        )
        self.assertRedirects(
            response, reverse("instances:instance", args=[self.instance.id]) + "#resize"
        )

        del self.instance.vcpu
        del self.instance.cur_vcpu

        # no changes as user reached quota
        self.assertEqual(self.instance.vcpu, vcpu)
        self.assertEqual(self.instance.cur_vcpu, cur_vcpu)

    def test_resize_memory(self):
        self.assertEqual(self.instance.memory, 128)
        self.assertEqual(self.instance.cur_memory, 128)

        response = self.client.post(
            reverse("instances:resize_memory", args=[self.instance.id]),
            {"memory": 512, "cur_memory": 256},
        )
        self.assertRedirects(
            response, reverse("instances:instance", args=[self.instance.id]) + "#resize"
        )

        del self.instance.memory
        del self.instance.cur_memory
        self.assertEqual(self.instance.memory, 512)
        self.assertEqual(self.instance.cur_memory, 256)

        response = self.client.post(
            reverse("instances:resize_memory", args=[self.instance.id]),
            {"memory_custom": 500, "cur_memory_custom": 200},
        )
        self.assertRedirects(
            response, reverse("instances:instance", args=[self.instance.id]) + "#resize"
        )

        del self.instance.memory
        del self.instance.cur_memory

        self.assertEqual(self.instance.memory, 500)
        self.assertEqual(self.instance.cur_memory, 200)

    def test_resize_memory_with_quota(self):
        # test for non admin user with quotas
        memory = self.instance.memory
        cur_memory = self.instance.cur_memory

        UserInstance.objects.create(
            user=self.test_user, instance=self.instance, is_change=True
        )

        self.client.force_login(self.test_user)

        response = self.client.post(
            reverse("instances:resize_memory", args=[self.instance.id]),
            {"memory": 512, "cur_memory": 256},
        )
        self.assertRedirects(
            response, reverse("instances:instance", args=[self.instance.id]) + "#resize"
        )

        del self.instance.memory
        del self.instance.cur_memory

        # no changes as user reached quota
        self.assertEqual(self.instance.memory, memory)
        self.assertEqual(self.instance.cur_memory, cur_memory)

    def test_resize_disk(self):
        self.assertEqual(self.instance.disks[0]["size"], 1024**3)

        response = self.client.post(
            reverse("instances:resize_disk", args=[self.instance.id]),
            {
                "disk_size_vda": 2,
            },
        )
        self.assertRedirects(
            response, reverse("instances:instance", args=[self.instance.id]) + "#resize"
        )

        del self.instance.disks
        self.assertEqual(self.instance.disks[0]["size"], 2 * 1024**3)

    def test_resize_disk_with_quota(self):
        # test for non admin user with quotas
        disk_size = self.instance.disks[0]["size"]
        UserInstance.objects.create(
            user=self.test_user, instance=self.instance, is_change=True
        )

        self.client.force_login(self.test_user)

        response = self.client.post(
            reverse("instances:resize_disk", args=[self.instance.id]),
            {
                "disk_size_vda": 3,
            },
        )
        self.assertRedirects(
            response, reverse("instances:instance", args=[self.instance.id]) + "#resize"
        )

        # no changes as user reached quota
        del self.instance.disks
        self.assertEqual(self.instance.disks[0]["size"], disk_size)

    def test_add_delete_new_volume(self):
        self.assertEqual(len(self.instance.disks), 1)

        response = self.client.post(
            reverse("instances:add_new_vol", args=[self.instance.id]),
            {
                "storage": "default",
                "name": "test-volume-2",
                "size": 1,
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.disks
        self.assertEqual(len(self.instance.disks), 2)

        response = self.client.post(
            reverse("instances:delete_vol", args=[self.instance.id]),
            {
                "storage": "default",
                "dev": "vdb",
                "name": "test-volume-2.qcow2",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.disks
        self.assertEqual(len(self.instance.disks), 1)

    def test_detach_attach_volume(self):
        # detach volume
        response = self.client.post(
            reverse("instances:detach_vol", args=[self.instance.id]),
            {
                "dev": "vda",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.disks
        self.assertEqual(len(self.instance.disks), 0)

        # reattach volume
        response = self.client.post(
            reverse("instances:add_existing_vol", args=[self.instance.id]),
            {
                "selected_storage": "default",
                "vols": "test-volume.qcow2",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.disks
        self.assertEqual(len(self.instance.disks), 1)

    def test_edit_volume(self):
        response = self.client.post(
            reverse("instances:edit_volume", args=[self.instance.id]),
            {
                "vol_path": "/var/lib/libvirt/images/test-volume.qcow2",
                # 'vol_shareable': False,
                # 'vol_readonly': False,
                "vol_bus": "virtio",
                "vol_bus_old": "virtio",
                "vol_format": "qcow2",
                "dev": "vda",
                "edit_volume": True,
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

    def test_attach_detach_cdrom(self):
        self.assertEqual(len(self.instance.media), 1)

        response = self.client.post(
            reverse("instances:add_cdrom", args=[self.instance.id]),
            {
                "bus": "sata",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.media
        self.assertEqual(len(self.instance.media), 2)

        # create dummy iso
        # with tempfile.NamedTemporaryFile() as f:
        #     f.write(b'\x00' * 1024**2)

        #     response = self.client.post(
        #         reverse('storage', args=[instance.compute.id, 'default']),
        #         {
        #             'iso_upload': True,
        #             'file': f
        #         },
        #     )

        # detach CD-ROM drive
        response = self.client.post(
            reverse("instances:detach_cdrom", args=[self.instance.id, "sda"]),
            {},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.media
        self.assertEqual(len(self.instance.media), 1)

    def test_snapshots(self):
        self.assertEqual(len(self.instance.snapshots), 0)

        response = self.client.post(
            reverse("instances:snapshot", args=[self.instance.id]),
            {
                "name": "test-snapshot",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.snapshots
        self.assertEqual(len(self.instance.snapshots), 1)

        response = self.client.post(
            reverse("instances:revert_snapshot", args=[self.instance.id]),
            {
                "name": "test-snapshot",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            reverse("instances:delete_snapshot", args=[self.instance.id]),
            {
                "name": "test-snapshot",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.snapshots
        self.assertEqual(len(self.instance.snapshots), 0)

    def test_autostart(self):
        self.assertEqual(self.instance.autostart, 0)

        response = self.client.post(
            reverse("instances:set_autostart", args=[self.instance.id]),
            {},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.autostart
        self.assertEqual(self.instance.autostart, 1)

        response = self.client.post(
            reverse("instances:unset_autostart", args=[self.instance.id]),
            {},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.autostart
        self.assertEqual(self.instance.autostart, 0)

    def test_bootmenu(self):
        self.assertEqual(self.instance.bootmenu, True)

        response = self.client.post(
            reverse("instances:unset_bootmenu", args=[self.instance.id]),
            {},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.bootmenu
        self.assertEqual(self.instance.bootmenu, False)

        response = self.client.post(
            reverse("instances:set_bootmenu", args=[self.instance.id]),
            {},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.bootmenu
        self.assertEqual(self.instance.bootmenu, True)

    def test_guest_agent(self):
        self.assertEqual(self.instance.guest_agent, False)

        response = self.client.post(
            reverse("instances:set_guest_agent", args=[self.instance.id]),
            {"guest_agent": True},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.guest_agent
        self.assertEqual(self.instance.guest_agent, True)

        response = self.client.post(
            reverse("instances:set_guest_agent", args=[self.instance.id]),
            {"guest_agent": False},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.guest_agent
        self.assertEqual(self.instance.guest_agent, False)

    def test_video_model(self):
        self.assertEqual(self.instance.video_model, "vga")

        response = self.client.post(
            reverse("instances:set_video_model", args=[self.instance.id]),
            {"video_model": "virtio"},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.video_model
        self.assertEqual(self.instance.video_model, "virtio")

    def test_owner(self):
        self.assertEqual(UserInstance.objects.count(), 0)
        response = self.client.post(
            reverse("instances:add_owner", args=[self.instance.id]),
            {"user_id": self.admin_user.id},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UserInstance.objects.count(), 1)

        user_instance: UserInstance = UserInstance.objects.get(id=1)
        self.assertEqual(user_instance.instance_id, self.instance.id)
        self.assertEqual(user_instance.user_id, self.admin_user.id)

        # test when no multiple owners allowed
        setting = AppSettings.objects.get(key="ALLOW_INSTANCE_MULTIPLE_OWNER")
        setting.value = "False"
        setting.save()

        response = self.client.post(
            reverse("instances:add_owner", args=[self.instance.id]),
            {"user_id": self.test_user.id},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UserInstance.objects.count(), 1)

        response = self.client.post(
            reverse("instances:del_owner", args=[self.instance.id]),
            {"userinstance": user_instance.id},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UserInstance.objects.count(), 0)

    def test_clone(self):
        instance_count = Instance.objects.count()
        response = self.client.post(
            reverse("instances:clone", args=[self.instance.id]),
            {
                "name": "test-vm-clone",
                "clone-net-mac-0": "de:ad:be:ef:de:ad",
                "disk-vda": "test-clone.img",
                "clone-title": "",
                "clone-description": "",
                "clone": "",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Instance.objects.count(), instance_count + 1)

        clone_qs = Instance.objects.filter(name="test-vm-clone")
        self.assertEqual(len(clone_qs), 1)
        clone = clone_qs[0]

        self.assertEqual(clone.proxy.get_net_devices()[0]["mac"], "de:ad:be:ef:de:ad")

        response = self.client.post(
            reverse("instances:snapshot", args=[clone.id]),
            {
                "name": "test",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            reverse("instances:destroy", args=[clone.id]),
            {"delete_disk": True, "delete_nvram": True},
            HTTP_REFERER=reverse("index"),
        )
        self.assertRedirects(response, reverse("instances:index"))
        self.assertEqual(Instance.objects.count(), instance_count)

    def test_clone_with_quota(self):
        # test for non admin user with quotas
        instance_count = Instance.objects.count()

        UserInstance.objects.create(user=self.test_user, instance=self.instance)

        self.client.force_login(self.test_user)

        response = self.client.post(
            reverse("instances:clone", args=[self.instance.id]),
            {
                "name": "test-vm-clone",
                "clone-net-mac-0": "de:ad:be:ef:de:ad",
                "disk-vda": "test-clone.img",
                "clone-title": "",
                "clone-description": "",
                "clone": "",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)
        # no new instances created as user reached quota
        self.assertEqual(Instance.objects.count(), instance_count)

    def test_clone_errors(self):
        instance_count = Instance.objects.count()

        # duplicate name
        response = self.client.post(
            reverse("instances:clone", args=[self.instance.id]),
            {
                "name": "test-vm",
                "clone-net-mac-0": "de:ad:be:ef:de:ad",
                "disk-vda": "test.img",
                "clone-title": "",
                "clone-description": "",
                "clone": "",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Instance.objects.count(), instance_count)

        # wrong name
        response = self.client.post(
            reverse("instances:clone", args=[self.instance.id]),
            {
                "name": "!@#$",
                "clone-net-mac-0": "de:ad:be:ef:de:ad",
                "disk-vda": "!@#$.img",
                "clone-title": "",
                "clone-description": "",
                "clone": "",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Instance.objects.count(), instance_count)

        # wrong mac
        response = self.client.post(
            reverse("instances:clone", args=[self.instance.id]),
            {
                "name": "test-vm-clone",
                "clone-net-mac-0": "gh:ad:be:ef:de:ad",
                "disk-vda": "test-clone.img",
                "clone-title": "",
                "clone-description": "",
                "clone": "",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Instance.objects.count(), instance_count)

    def test_console(self):
        response = self.client.post(
            reverse("instances:update_console", args=[self.instance.id]),
            {"type": "spice", "listen_on": "0.0.0.0", "password": "", "keymap": "auto"},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

    def test_status(self):
        response = self.client.get(reverse("instances:status", args=[self.instance.id]))
        self.assertEqual(response.status_code, 200)

    def test_stats(self):
        response = self.client.get(reverse("instances:stats", args=[self.instance.id]))
        self.assertEqual(response.status_code, 200)

    def test_guess_mac_address(self):
        response = self.client.get(
            reverse("instances:guess_mac_address", args=[self.instance.name])
        )
        self.assertEqual(response.status_code, 200)

    def test_random_mac_address(self):
        response = self.client.get(reverse("instances:random_mac_address"))
        self.assertEqual(response.status_code, 200)

    def test_guess_clone_name(self):
        response = self.client.get(reverse("instances:guess_clone_name"))
        self.assertEqual(response.status_code, 200)

    def test_sshkeys(self):
        UserSSHKey.objects.create(
            keyname="keyname", keypublic=self.rsa_key, user=self.test_user
        )
        UserInstance.objects.create(user=self.test_user, instance=self.instance)

        response = self.client.get(
            reverse("instances:sshkeys", args=[self.instance.id])
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            reverse("instances:sshkeys", args=[self.instance.id]) + "?plain=true"
        )
        self.assertEqual(response.status_code, 200)

    def test_check_instance(self):
        response = self.client.get(
            reverse("instances:check_instance", args=["test-vm"])
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"vname": "test-vm", "exists": True})

    def test_start_template(self):
        # starting templates must fail
        self.assertEqual(self.instance.status, 5)

        self.instance.is_template = True
        self.instance.save()

        response = self.client.get(
            reverse("instances:poweron", args=[self.instance.id]),
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.status
        self.assertEqual(self.instance.status, 5)

        self.instance.is_template = False
        self.instance.save()

    def test_power(self):
        # poweron
        self.assertEqual(self.instance.status, 5)

        response = self.client.get(
            reverse("instances:poweron", args=[self.instance.id]),
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.status

        self.assertEqual(self.instance.status, 1)

        # suspend
        response = self.client.get(
            reverse("instances:suspend", args=[self.instance.id]),
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.status
        self.assertEqual(self.instance.status, 3)

        # resume
        response = self.client.get(
            reverse("instances:resume", args=[self.instance.id]),
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.status
        self.assertEqual(self.instance.status, 1)

        # poweroff
        response = self.client.get(
            reverse("instances:poweroff", args=[self.instance.id]),
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        # as no OS is installed ACPI won't work
        del self.instance.status
        self.assertEqual(self.instance.status, 1)

        # powercycle
        response = self.client.get(
            reverse("instances:powercycle", args=[self.instance.id]),
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.status
        self.assertEqual(self.instance.status, 1)

        # force_off
        response = self.client.get(
            reverse("instances:force_off", args=[self.instance.id]),
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.status
        self.assertEqual(self.instance.status, 5)

    def test_vv_file(self):
        response = self.client.get(
            reverse("instances:getvvfile", args=[self.instance.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_vcpu_hotplug(self):
        response = self.client.post(
            reverse("instances:set_vcpu_hotplug", args=[self.instance.id]),
            {"vcpu_hotplug": "True"},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

    def test_change_network(self):
        self.assertEqual(self.instance.networks[0]["mac"], "52:54:00:a2:3c:e7")
        response = self.client.post(
            reverse("instances:change_network", args=[self.instance.id]),
            {
                "net-mac-0": "52:54:00:a2:3c:e8",
                "net-source-0": "net:default",
                "net-nwfilter-0": "",
                "net-model-0": "virtio",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.networks
        self.assertEqual(self.instance.networks[0]["mac"], "52:54:00:a2:3c:e8")

    def test_add_delete_network(self):
        self.assertEqual(len(self.instance.networks), 1)
        net_mac = self.instance.networks[0]["mac"]
        response = self.client.post(
            reverse("instances:add_network", args=[self.instance.id]),
            {
                "add-net-mac": "52:54:00:a2:3c:e9",
                "add-net-network": "net:default",
                "add_net-nwfilter": "",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.networks
        self.assertEqual(len(self.instance.networks), 2)
        self.assertEqual(self.instance.networks[1]["mac"], "52:54:00:a2:3c:e9")

        response = self.client.post(
            reverse("instances:delete_network", args=[self.instance.id]),
            {
                "delete_network": "52:54:00:a2:3c:e9",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.networks
        self.assertEqual(len(self.instance.networks), 1)
        self.assertEqual(self.instance.networks[0]["mac"], net_mac)

    def test_set_link_state(self):
        self.assertEqual(self.instance.networks[0]["state"], "up")
        response = self.client.post(
            reverse("instances:set_link_state", args=[self.instance.id]),
            {
                "mac": self.instance.networks[0]["mac"],
                "set_link_state": "up",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.networks
        self.assertEqual(self.instance.networks[0]["state"], "down")

    def test_set_unset_qos(self):
        self.assertEqual(len(self.instance.qos.keys()), 0)
        net_mac = self.instance.networks[0]["mac"]
        response = self.client.post(
            reverse("instances:set_qos", args=[self.instance.id]),
            {
                "net-mac-0": net_mac,
                "qos_direction": "inbound",
                "qos_average": 1,
                "qos_peak": 1,
                "qos_burst": 1,
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.qos
        self.assertEqual(len(self.instance.qos.keys()), 1)

        response = self.client.post(
            reverse("instances:unset_qos", args=[self.instance.id]),
            {
                "net-mac": net_mac,
                "qos_direction": "inbound",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)
        del self.instance.qos
        self.assertEqual(len(self.instance.qos.keys()), 0)

        # test on running instance
        # self.instance.proxy.start()
        # response = self.client.post(
        #     reverse('instances:set_qos', args=[self.instance.id]),
        #     {
        #         'net-mac-0': net_mac,
        #         'qos_direction': 'inbound',
        #         'qos_average': 1,
        #         'qos_peak': 1,
        #         'qos_burst': 1,
        #     },
        #     HTTP_REFERER=reverse('index'),
        # )
        # self.assertEqual(response.status_code, 302)
        # self.instance.proxy.force_shutdown()

    def test_change_options(self):
        self.assertEqual(self.instance.title, "")
        self.assertEqual(self.instance.description, "")

        response = self.client.post(
            reverse("instances:change_options", args=[self.instance.id]),
            {
                "title": "test-vm-title",
                "description": "test-vm description",
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        del self.instance.title
        del self.instance.description

        self.assertEqual(self.instance.title, "test-vm-title")
        self.assertEqual(self.instance.description, "test-vm description")

    def test_flavors(self):
        response = self.client.get(reverse("instances:flavor_create"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("instances:flavor_create"),
            {
                "label": "test_flavor",
                "memory": 256,
                "vcpu": 1,
                "disk": 10,
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        id = Flavor.objects.last().id

        response = self.client.get(reverse("instances:flavor_update", args=[id]))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("instances:flavor_update", args=[id]),
            {
                "label": "test_flavor_",
                "memory": 256,
                "vcpu": 1,
                "disk": 10,
            },
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.get(reverse("instances:flavor_delete", args=[id]))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("instances:flavor_delete", args=[id]),
            {},
            HTTP_REFERER=reverse("index"),
        )
        self.assertEqual(response.status_code, 302)

    # def donot_test_instance(self):
    #     compute: Compute = Compute.objects.get(pk=1)
    #     user: User = User.objects.get(pk=1)

    #     # delete started instance with disks
    #     self.instance.proxy.start()
    #     del self.instance.status
    #     self.assertEqual(self.instance.status, 1)

    # # create volume
    # response = self.client.post(
    #     reverse('create_volume', args=[compute.id, 'default']),
    #     {
    #         'name': 'test3',
    #         'format': 'qcow2',
    #         'size': '1',
    #         'meta_prealloc': False,
    #     },
    # )
    # self.assertRedirects(response, reverse('storage', args=[compute.id, 'default']))

    # # delete volume
    # response = self.client.post(
    #     reverse('instances:delete_vol', args=[instance.id]),
    #     {
    #         'storage': 'default',
    #         'dev': 'vdb',
    #         'name': 'test3.qcow2',
    #     },
    #     HTTP_REFERER=reverse('index'),
    # )
    # self.assertEqual(response.status_code, 302)

    # , list(response.context['messages'])[0]
