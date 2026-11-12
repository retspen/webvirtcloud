from computes.models import Compute
from django.conf import settings
from instances.models import Flavor, Instance
from instances.utils import nic_macs
from libvirt import libvirtError
from rest_framework import serializers


class InstanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instance
        fields = ["id", "compute", "name", "uuid", "is_template", "created", "drbd"]


# what a VM's device dicts tell of the host: its files and pools
HOST_KEYS = {"image", "storage", "path", "backing_file", "loader"}


class InstanceDetailsSerializer(serializers.ModelSerializer):
    networks = serializers.SerializerMethodField()

    def get_networks(self, instance) -> list[dict]:
        """Each NIC with its addresses (None: none known), which the VM page
        reads after it loads (views.nic_addresses)."""
        try:
            found = instance.proxy.get_addresses()
        except libvirtError:
            found = {}
        return [{**nic, **dict(zip(("ipv4", "ipv6"), found.get(nic["mac"], (None, None))))} for nic in instance.networks]

    def superuser(self):
        request = self.context.get("request")
        return bool(request and request.user.is_superuser)

    def get_fields(self):
        fields = super().get_fields()
        # the host's files are a superuser's, as on the VM page: its ISO images and the VM's NVRAM file
        if not self.superuser():
            del fields["media_iso"], fields["nvram"]
        return fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.superuser():  # a disk's, CD-ROM's and firmware's file and pool too
            for field in ("disks", "media"):
                data[field] = [{key: value for key, value in device.items() if key not in HOST_KEYS}
                               for device in data[field]]
            data["firmware"] = {key: value for key, value in data["firmware"].items() if key not in HOST_KEYS}
            for snap in data["snapshots"]:  # the disks a revert detaches, by device
                snap["detaches"] = [{"dev": disk["dev"]} for disk in snap.get("detaches", [])]
        return data

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
        fields = ["id", "label", "memory", "vcpu", "disk"]
        # as the web form (instances.forms.FlavorForm): MiB, vCPUs and GiB, each at least 1
        extra_kwargs = {"memory": {"min_value": 1}, "vcpu": {"min_value": 1}, "disk": {"min_value": 1}}


class DestroyOptionsSerializer(serializers.Serializer):
    """What a VM's delete takes besides the VM: from the web form's checkboxes
    or an API body, JSON or form-encoded ("false" is false)."""

    delete_disk = serializers.BooleanField(default=False)
    delete_nvram = serializers.BooleanField(default=False)


class PowerOnSerializer(serializers.Serializer):
    """Power On's options, from the page's form or an API body: fresh boots
    a VM with a saved state anew and discards the saved state."""

    fresh = serializers.BooleanField(default=False)


class DestroySerializer(DestroyOptionsSerializer):
    """The API's delete: a job, which a new submission key per request names."""

    submission_key = serializers.CharField(write_only=True)


class CreateInstanceSerializer(serializers.Serializer):
    """The API's VM create: the new VM form's fields, as a job."""

    name = serializers.CharField(max_length=64)
    # BIOS, UEFI or UEFI Secure Boot, as the host offers; left out: the machine's default
    firmware = serializers.CharField(required=False)
    tpm = serializers.BooleanField(required=False)
    vcpu = serializers.IntegerField(min_value=1)
    vcpu_mode = serializers.CharField(max_length=64)
    memory = serializers.IntegerField(min_value=1)
    networks = serializers.CharField(max_length=256)
    mac = serializers.CharField(allow_blank=True, max_length=255, required=False)
    nwfilter = serializers.CharField(allow_blank=True, max_length=256, required=False)
    storage = serializers.CharField(initial="default")
    hdd_size = serializers.IntegerField(min_value=1, required=False)
    cache_mode = serializers.CharField(initial="none")
    meta_prealloc = serializers.BooleanField(required=False)
    virtio = serializers.BooleanField(initial=True)
    qemu_ga = serializers.BooleanField(initial=True)
    cloud_init = serializers.BooleanField(required=False)
    video = serializers.CharField(initial="vga")
    listener_addr = serializers.ChoiceField(choices=settings.QEMU_CONSOLE_LISTENER_ADDRESSES)
    submission_key = serializers.CharField(write_only=True)

    def validate(self, attrs):
        try:
            nic_macs(attrs.get("mac"), attrs.get("networks", ""))
        except ValueError as err:
            raise serializers.ValidationError({"mac": str(err)})
        return attrs


class MigrateSerializer(serializers.Serializer):
    instance = serializers.PrimaryKeyRelatedField(queryset=Instance.objects.all())
    target_compute = serializers.PrimaryKeyRelatedField(queryset=Compute.objects.all())
    live = serializers.BooleanField(default=True)
    offline = serializers.BooleanField(default=False)
    # left out, also from a form-encoded request: auto converge on
    autoconverge = serializers.BooleanField(default=True)
    compress = serializers.BooleanField(default=False)
    unsafe = serializers.BooleanField(default=False)
    # {target: pool of the destination} of the disks copied there; delete_source deletes their source files
    disk_pools = serializers.DictField(child=serializers.CharField(allow_blank=True), default=dict)
    delete_source = serializers.BooleanField(default=False)
    submission_key = serializers.CharField(write_only=True)
