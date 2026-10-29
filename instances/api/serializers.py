from instances.models import CreateInstance, Flavor, Instance, MigrateInstance
from instances.utils import nic_macs
from rest_framework import serializers


class InstanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instance
        fields = ["id", "compute", "name", "uuid", "is_template", "created", "drbd"]


class InstanceDetailsSerializer(serializers.ModelSerializer):
    def get_fields(self):
        fields = super().get_fields()
        # the host's ISO images are a superuser's, as on the VM page; reading
        # them refreshes every pool of the host
        request = self.context.get("request")
        if not (request and request.user.is_superuser):
            del fields["media_iso"]
        return fields

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


class CreateInstanceSerializer(serializers.ModelSerializer):
    video = serializers.CharField(initial="vga")
    storage = serializers.CharField(initial="default")
    cache_mode = serializers.CharField(initial="none")
    virtio = serializers.BooleanField(initial=True)
    qemu_ga = serializers.BooleanField(initial=True)
    submission_key = serializers.CharField(write_only=True)

    def validate(self, attrs):
        try:
            nic_macs(attrs.get("mac"), attrs.get("networks", ""))
        except ValueError as err:
            raise serializers.ValidationError({"mac": str(err)})
        return attrs

    class Meta:
        model = CreateInstance
        fields = [
            "name",
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
            "cloud_init",
            "video",
            "listener_addr",
            "submission_key",
        ]


class MigrateSerializer(serializers.ModelSerializer):
    instance = Instance.objects.all().prefetch_related("userinstance_set")
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

    class Meta:
        model = MigrateInstance
        fields = [
            "instance",
            "target_compute",
            "live",
            "offline",
            "autoconverge",
            "compress",
            "unsafe",
            "disk_pools",
            "delete_source",
            "submission_key",
        ]
