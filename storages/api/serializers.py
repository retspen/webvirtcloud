from rest_framework import serializers


class StoragesSerializer(serializers.Serializer):
    """A storage pool as the API lists it."""

    name = serializers.CharField(max_length=20)
    status = serializers.IntegerField()
    type = serializers.CharField(max_length=100)
    size = serializers.IntegerField(help_text="Capacity in bytes")
    volumes = serializers.IntegerField()


class StorageSerializer(serializers.Serializer):
    """A storage pool's details."""

    state = serializers.IntegerField()
    size = serializers.IntegerField(help_text="Capacity in bytes")
    free = serializers.IntegerField(help_text="Free space in bytes")
    status = serializers.CharField(max_length=128)
    path = serializers.CharField(max_length=128)
    type = serializers.CharField(max_length=128)
    autostart = serializers.BooleanField()
    # the pool's volumes (wvmStorage.update_volumes); none while it is stopped
    volumes = serializers.ListField(child=serializers.DictField(), read_only=True, allow_null=True)


class VolumeSerializer(serializers.Serializer):
    """A volume as the API reads it."""

    name = serializers.CharField()
    type = serializers.CharField()
    allocation = serializers.IntegerField(help_text="Bytes the volume takes in its pool")
    size = serializers.IntegerField(help_text="Capacity in bytes")


class CreateVolumeSerializer(serializers.Serializer):
    """A new volume, as the web form (storages.forms.CreateVolumeForm) takes it:
    its size in GiB, where a volume read back tells bytes."""

    name = serializers.RegexField(r"^[a-zA-Z0-9._-]+$", max_length=120)
    type = serializers.ChoiceField(choices=[("qcow2", "qcow2 (recommended)"), ("qcow", "qcow"), ("raw", "raw")],
                                   label="Format")
    size = serializers.IntegerField(min_value=1, help_text="Capacity in GiB")
    meta_prealloc = serializers.BooleanField(default=False)
