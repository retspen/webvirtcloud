import tempfile

from django.shortcuts import reverse
from django.test import TestCase

from computes.models import Compute

from .models import Instance


class InstancesTestCase(TestCase):
    def setUp(self):
        self.client.login(username='admin', password='admin')
        Compute(
            name='local',
            hostname='localhost',
            login='',
            password='',
            details='local',
            type=4,
        ).save()

    def test_index(self):
        response = self.client.get(reverse('instances:index'))
        # with open('index.html', 'wb') as f:
        #     f.write(response.content)
        self.assertEqual(response.status_code, 200)

    def test_create_select_type(self):
        response = self.client.get(reverse('instances:create_instance_select_type', args=[1]))
        self.assertEqual(response.status_code, 200)

    def test_instance(self):
        compute = Compute.objects.get(pk=1)

        # create volume
        response = self.client.post(
            reverse('create_volume', args=[compute.id, 'default']),
            {
                'name': 'test',
                'format': 'qcow2',
                'size': '1',
                'meta_prealloc': False,
            },
        )
        self.assertRedirects(response, reverse('storage', args=[compute.id, 'default']))

        # create instance
        response = self.client.get(reverse('instances:create_instance', args=[compute.id, 'x86_64', 'q35']))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse('instances:create_instance', args=[compute.id, 'x86_64', 'q35']),
            {
                'name': 'test',
                'firmware': 'BIOS',
                'vcpu': 1,
                'vcpu_mode': 'host-model',
                'memory': 512,
                'device0': 'disk',
                'bus0': 'virtio',
                'images': 'test.qcow2',
                'storage-control': 'default',
                'image-control': 'test.qcow2',
                'networks': 'default',
                'network-control': 'default',
                'cache_mode': 'directsync',
                'nwfilter': '',
                'graphics': 'spice',
                'video': 'vga',
                'listener_addr': '0.0.0.0',
                'console_pass': '',
                'qemu_ga': False,
                'virtio': True,
                'create': True,
            },
        )
        self.assertEqual(response.status_code, 302)

        instance: Instance = Instance.objects.get(pk=1)
        self.assertEqual(instance.name, 'test')

        # get instance page
        response = self.client.get(reverse('instances:instance', args=[instance.id]))
        self.assertEqual(response.status_code, 200)

        # resize cpu
        self.assertEqual(instance.vcpu, 1)
        self.assertEqual(instance.cur_vcpu, 1)

        response = self.client.post(reverse('instances:resizevm_cpu', args=[instance.id]), {'vcpu': 4, 'cur_vcpu': 2})
        self.assertRedirects(response, reverse('instances:instance', args=[instance.id]) + '#resize')

        # reset cached properties
        del instance.vcpu
        del instance.cur_vcpu
        self.assertEqual(instance.vcpu, 4)
        self.assertEqual(instance.cur_vcpu, 2)

        # resize memory
        self.assertEqual(instance.memory, 512)
        self.assertEqual(instance.cur_memory, 512)

        response = self.client.post(reverse('instances:resize_memory', args=[instance.id]), {
            'memory': 2048,
            'cur_memory': 1024
        })
        self.assertRedirects(response, reverse('instances:instance', args=[instance.id]) + '#resize')

        del instance.memory
        del instance.cur_memory
        self.assertEqual(instance.memory, 2048)
        self.assertEqual(instance.cur_memory, 1024)

        # resize disk
        self.assertEqual(instance.disks[0]['size'], 1024**3)

        response = self.client.post(reverse('instances:resize_disk', args=[instance.id]), {
            'disk_size_vda': '2.0 GB',
        })
        self.assertRedirects(response, reverse('instances:instance', args=[instance.id]) + '#resize')

        del instance.disks
        self.assertEqual(instance.disks[0]['size'], 2 * 1024**3)

        # add new volume
        self.assertEqual(len(instance.disks), 1)

        response = self.client.post(
            reverse('instances:add_new_vol', args=[instance.id]),
            {
                'storage': 'default',
                'name': 'test2',
                'size': 1,
            },
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.disks
        self.assertEqual(len(instance.disks), 2)

        # delete volume from instance
        response = self.client.post(
            reverse('instances:delete_vol', args=[instance.id]),
            {
                'storage': 'default',
                'dev': 'vdb',
                'name': 'test2.qcow2',
            },
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.disks
        self.assertEqual(len(instance.disks), 1)

        # detach volume
        response = self.client.post(
            reverse('instances:detach_vol', args=[instance.id]),
            {
                'dev': 'vda',
            },
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.disks
        self.assertEqual(len(instance.disks), 0)

        # add existing volume
        response = self.client.post(
            reverse('instances:add_existing_vol', args=[instance.id]),
            {
                'selected_storage': 'default',
                'vols': 'test.qcow2',
            },
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.disks
        self.assertEqual(len(instance.disks), 1)

        # edit volume
        response = self.client.post(
            reverse('instances:edit_volume', args=[instance.id]),
            {
                'vol_path': '/var/lib/libvirt/images/test.qcow2',
                # 'vol_shareable': False,
                # 'vol_readonly': False,
                'vol_bus': 'virtio',
                'vol_bus_old': 'virtio',
                'vol_format': 'qcow2',
                'dev': 'vda',
                'edit_volume': True
            },
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        # add media device
        self.assertEqual(len(instance.media), 1)

        response = self.client.post(
            reverse('instances:add_cdrom', args=[instance.id]),
            {
                'bus': 'sata',
            },
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.media
        self.assertEqual(len(instance.media), 2)

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

        # remove media device
        response = self.client.post(
            reverse('instances:detach_cdrom', args=[instance.id, 'sda']),
            {},
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.media
        self.assertEqual(len(instance.media), 1)

        # snapshots
        self.assertEqual(len(instance.snapshots), 0)

        response = self.client.post(
            reverse('instances:snapshot', args=[instance.id]),
            {
                'name': 'test',
            },
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.snapshots
        self.assertEqual(len(instance.snapshots), 1)

        response = self.client.post(
            reverse('instances:revert_snapshot', args=[instance.id]),
            {
                'name': 'test',
            },
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            reverse('instances:delete_snapshot', args=[instance.id]),
            {
                'name': 'test',
            },
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.snapshots
        self.assertEqual(len(instance.snapshots), 0)

        # autostart
        self.assertEqual(instance.autostart, 0)

        response = self.client.post(
            reverse('instances:set_autostart', args=[instance.id]),
            {},
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.autostart
        self.assertEqual(instance.autostart, 1)

        response = self.client.post(
            reverse('instances:unset_autostart', args=[instance.id]),
            {},
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.autostart
        self.assertEqual(instance.autostart, 0)

        # bootmenu
        self.assertEqual(instance.bootmenu, True)

        response = self.client.post(
            reverse('instances:unset_bootmenu', args=[instance.id]),
            {},
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.bootmenu
        self.assertEqual(instance.bootmenu, False)

        response = self.client.post(
            reverse('instances:set_bootmenu', args=[instance.id]),
            {},
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.bootmenu
        self.assertEqual(instance.bootmenu, True)

        # guest agent

        self.assertEqual(instance.guest_agent, False)

        response = self.client.post(
            reverse('instances:set_guest_agent', args=[instance.id]),
            {'guest_agent': True},
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.guest_agent
        self.assertEqual(instance.guest_agent, True)

        response = self.client.post(
            reverse('instances:set_guest_agent', args=[instance.id]),
            {'guest_agent': False},
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.guest_agent
        self.assertEqual(instance.guest_agent, False)

        # video model
        self.assertEqual(instance.video_model, 'vga')

        response = self.client.post(
            reverse('instances:set_video_model', args=[instance.id]),
            {'video_model': 'virtio'},
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        del instance.video_model
        self.assertEqual(instance.video_model, 'virtio')

        # console
        response = self.client.post(
            reverse('instances:update_console', args=[instance.id]),
            {
                'type': 'spice',
                'listen_on': '0.0.0.0',
                'password': '',
                'keymap': 'auto'
            },
            HTTP_REFERER=reverse('index'),
        )
        self.assertEqual(response.status_code, 302)

        # poweron
        self.assertEqual(instance.status, 5)

        response = self.client.get(reverse('instances:poweron', args=[instance.id]), HTTP_REFERER=reverse('index'))
        self.assertEqual(response.status_code, 302)

        del instance.status

        self.assertEqual(instance.status, 1)

        # status
        response = self.client.get(reverse('instances:status', args=[instance.id]))
        self.assertEqual(response.status_code, 200)

        # stats
        response = self.client.get(reverse('instances:stats', args=[instance.id]))
        self.assertEqual(response.status_code, 200)

        # guess_mac_address
        response = self.client.get(reverse('instances:guess_mac_address', args=[instance.name]))
        self.assertEqual(response.status_code, 200)

        # random_mac_address
        response = self.client.get(reverse('instances:random_mac_address'))
        self.assertEqual(response.status_code, 200)

        # random_mac_address
        response = self.client.get(reverse('instances:guess_clone_name'))
        self.assertEqual(response.status_code, 200)

        # guess_mac_address
        response = self.client.get(reverse('instances:check_instance', args=[instance.name]))
        self.assertEqual(response.status_code, 200)

        # sshkeys
        response = self.client.get(reverse('instances:sshkeys', args=[instance.name]))
        self.assertEqual(response.status_code, 200)

        # suspend
        response = self.client.get(reverse('instances:suspend', args=[instance.id]), HTTP_REFERER=reverse('index'))
        self.assertEqual(response.status_code, 302)

        del instance.status
        self.assertEqual(instance.status, 3)

        # resume
        response = self.client.get(reverse('instances:resume', args=[instance.id]), HTTP_REFERER=reverse('index'))
        self.assertEqual(response.status_code, 302)

        del instance.status
        self.assertEqual(instance.status, 1)

        # poweroff
        response = self.client.get(reverse('instances:poweroff', args=[instance.id]), HTTP_REFERER=reverse('index'))
        self.assertEqual(response.status_code, 302)

        # as no OS is installed ACPI won't work
        del instance.status
        self.assertEqual(instance.status, 1)

        # powercycle
        response = self.client.get(reverse('instances:powercycle', args=[instance.id]), HTTP_REFERER=reverse('index'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(instance.status, 1)

        # force_off
        response = self.client.get(reverse('instances:force_off', args=[instance.id]), HTTP_REFERER=reverse('index'))
        self.assertEqual(response.status_code, 302)

        del instance.status
        self.assertEqual(instance.status, 5)

        # delete started instance with disks
        instance.proxy.start()
        del instance.status
        self.assertEqual(instance.status, 1)

        response = self.client.post(
            reverse('instances:destroy', args=[instance.id]),
            {'delete_disk': True},
            HTTP_REFERER=reverse('index'),
        )
        self.assertRedirects(response, reverse('instances', args=[compute.id]))

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
