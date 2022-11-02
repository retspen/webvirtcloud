from rest_framework import serializers
from networks.models import Networks


class NetworksSerializer(serializers.ModelSerializer):
    class Meta:
        model = Networks
        fields = ["name", "status", "device", "forward"]
