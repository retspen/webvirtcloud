from computes.models import Compute
from rest_framework import serializers
from vrtManager.connection import CONN_SOCKET, CONN_SSH, CONN_TCP, CONN_TLS


class ComputeSerializer(serializers.ModelSerializer):
    # Use <input type="password"> for the input.
    password = serializers.CharField(style={"input_type": "password"})
    # Use a radio input instead of a select input.
    conn_types = (
        (CONN_SSH, "SSH"),
        (CONN_TCP, "TCP"),
        (CONN_TLS, "TLS"),
        (CONN_SOCKET, "SOCK"),
    )
    type = serializers.ChoiceField(choices=conn_types)

    class Meta:
        model = Compute
        fields = ["id", "name", "hostname", "login", "password", "type", "details"]
