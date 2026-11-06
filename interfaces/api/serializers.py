from rest_framework import serializers


class InterfacesSerializer(serializers.Serializer):
    """A host interface as the API lists it."""

    name = serializers.CharField(max_length=20)
    type = serializers.CharField(max_length=12)
    state = serializers.CharField(max_length=100)
    mac = serializers.CharField(max_length=24)
