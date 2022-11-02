from instances.models import CreateInstance, Flavor, Instance, MigrateInstance
from rest_framework import serializers


class InstanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instance
        fields = ["id", "compute", "name", "uuid", "is_template", "created", "drbd"]


class InstanceDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instance
        fields = [
            "id",
            "compute",
            "status",
            "uuid",
            "name",
            "title",
            "description",
            "is_template",
            "created",
            "drbd",
            "arch",
            "machine",
            "vcpu",
            "memory",
            "firmware",
            "nvram",
            "bootmenu",
            "boot_order",
            "disks",
            "media",
            "media_iso",
            "snapshots",
            "networks",
            "console_type",
            "console_port",
            "console_keymap",
            "console_listener_address",
            "video_model",
            "guest_agent_ready",
            "autostart",
        ]


class FlavorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Flavor
        fields = ["label", "memory", "vcpu", "disk"]


class CreateInstanceSerializer(serializers.ModelSerializer):
    firmware_choices = (
        ("", "BIOS"),
        # ('UEFI', 'UEFI'),
    )
    firmware = serializers.ChoiceField(choices=firmware_choices)
    graphics = serializers.CharField(initial="vnc")
    video = serializers.CharField(initial="vga")
    storage = serializers.CharField(initial="default")
    cache_mode = serializers.CharField(initial="none")
    virtio = serializers.BooleanField(initial=True)
    qemu_ga = serializers.BooleanField(initial=True)

    class Meta:
        model = CreateInstance
        fields = [
            "name",
            "firmware",
            "vcpu",
            "vcpu_mode",
            "memory",
            "networks",
            "mac",
            "nwfilter",
            "storage",
            "hdd_size",
            "cache_mode",
            "meta_prealloc",
            "virtio",
            "qemu_ga",
            "console_pass",
            "graphics",
            "video",
            "listener_addr",
        ]


class MigrateSerializer(serializers.ModelSerializer):
    instance = Instance.objects.all().prefetch_related("userinstance_set")
    live = serializers.BooleanField(initial=True)
    xml_del = serializers.BooleanField(initial=True)

    class Meta:
        model = MigrateInstance
        fields = [
            "instance",
            "target_compute",
            "live",
            "xml_del",
            "offline",
            "autoconverge",
            "compress",
            "postcopy",
            "unsafe",
        ]
