from rest_framework import serializers


class StatusSerializer(serializers.Serializer):
    """Response body of API actions that only report a status message."""

    status = serializers.CharField()


class ErrorSerializer(serializers.Serializer):
    """Response body of a refused request: why, as DRF's own errors."""

    detail = serializers.CharField()


class ActionStatusSerializer(StatusSerializer):
    """A VM action's status and what the web page would have shown after it,
    such as a disk that was kept or a template that was not started."""

    messages = serializers.ListField(child=serializers.CharField())
