from computes.models import Compute
from computes.validators import validate_gstfsd_key
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
    gstfsd_key = serializers.CharField(
        style={"input_type": "password"},
        write_only=True,
        required=False,
        allow_blank=True,
        validators=[validate_gstfsd_key],
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

    def validate_gstfsd_key(self, value):
        return value or (self.instance.gstfsd_key if self.instance else value)

    class Meta:
        model = Compute
        fields = ["id", "name", "hostname", "login", "password", "type", "details", "migration_address", "gstfsd_key"]
