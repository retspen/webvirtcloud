from networks.models import Networks
from rest_framework import serializers


class NetworksSerializer(serializers.ModelSerializer):
    class Meta:
        model = Networks
        fields = ["name", "status", "device", "forward"]
