
from rest_framework import serializers
from storages.models import Storages, Storage, Volume


class StoragesSerializer(serializers.ModelSerializer):

    class Meta:
        model = Storages
        fields = ['name', 'status', 'type', 'size', 'volumes']


class StorageSerializer(serializers.ModelSerializer):
    volumes = serializers.ReadOnlyField()
    class Meta:
        model = Storage
        fields = ['state', 'size', 'free', 'status', 'path', 'type', 'autostart', 'volumes'] 


class VolumeSerializer(serializers.ModelSerializer):
    # what the web form (storages.forms.CreateVolumeForm) takes
    name = serializers.RegexField(r"^[a-zA-Z0-9._-]+$", max_length=120)
    size = serializers.IntegerField(min_value=1)  # GiB
    allocation = serializers.ReadOnlyField()
    meta_prealloc = serializers.BooleanField(write_only=True, default=False)
    class Meta:
        model = Volume
        fields = ['name', 'type', 'allocation', 'size', 'meta_prealloc'] 
