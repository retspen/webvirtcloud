from rest_framework import serializers


class NetworksSerializer(serializers.Serializer):
    """A host network as the API lists it."""

    name = serializers.CharField(max_length=20)
    status = serializers.CharField(max_length=12)
    device = serializers.CharField(max_length=100)
    forward = serializers.CharField(max_length=24)
