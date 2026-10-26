from computes.models import Compute
from rest_framework import serializers
from vrtManager.connection import CONN_SOCKET, CONN_SSH, CONN_TCP, CONN_TLS


class ComputeSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        style={"input_type": "password"},
        write_only=True,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    # Use a radio input instead of a select input.
    conn_types = (
        (CONN_SSH, "SSH"),
        (CONN_TCP, "TCP"),
        (CONN_TLS, "TLS"),
        (CONN_SOCKET, "SOCK"),
    )
    type = serializers.ChoiceField(choices=conn_types)

    def validate_password(self, value):
        # as on the web form, an empty password on an edit keeps the stored one
        return value or (self.instance.password if self.instance else value)

    class Meta:
        model = Compute
        fields = ["id", "name", "hostname", "login", "password", "type", "details", "migration_address"]
