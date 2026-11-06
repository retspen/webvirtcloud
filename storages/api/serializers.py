from rest_framework import serializers


class StoragesSerializer(serializers.Serializer):
    """A storage pool as the API lists it."""

    name = serializers.CharField(max_length=20)
    status = serializers.IntegerField()
    type = serializers.CharField(max_length=100)
    size = serializers.IntegerField()
    volumes = serializers.IntegerField()


class StorageSerializer(serializers.Serializer):
    """A storage pool's details."""

    state = serializers.IntegerField()
    size = serializers.IntegerField()
    free = serializers.IntegerField()
    status = serializers.CharField(max_length=128)
    path = serializers.CharField(max_length=128)
    type = serializers.CharField(max_length=128)
    autostart = serializers.BooleanField()
    # the pool's volumes (wvmStorage.update_volumes); none while it is stopped
    volumes = serializers.ListField(child=serializers.DictField(), read_only=True, allow_null=True)


class VolumeSerializer(serializers.Serializer):
    # what the web form (storages.forms.CreateVolumeForm) takes
    name = serializers.RegexField(r"^[a-zA-Z0-9._-]+$", max_length=120)
    type = serializers.ChoiceField(choices=[("qcow2", "qcow2 (recommended)"), ("qcow", "qcow"), ("raw", "raw")],
                                   label="Format")
    allocation = serializers.IntegerField(read_only=True)
    size = serializers.IntegerField(min_value=1)  # GiB
    meta_prealloc = serializers.BooleanField(write_only=True, default=False)
