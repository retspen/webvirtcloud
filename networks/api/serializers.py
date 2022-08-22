
from rest_framework import serializers
from networks.models import Networks


class NetworksSerializer(serializers.ModelSerializer):
        
    class Meta:
        model = Networks
        fields = ['name', 'status', 'device', 'forward'] 



# class VolumeSerializer(serializers.ModelSerializer):
#     allocation = serializers.ReadOnlyField()
#     meta_prealloc = serializers.BooleanField(write_only=True)
#     class Meta:
#         model = Volume
#         fields = ['name', 'type', 'allocation', 'size', 'meta_prealloc'] 
