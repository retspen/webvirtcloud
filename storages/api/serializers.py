
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
    allocation = serializers.ReadOnlyField()
    meta_prealloc = serializers.BooleanField(write_only=True)
    class Meta:
        model = Volume
        fields = ['name', 'type', 'allocation', 'size', 'meta_prealloc'] 
