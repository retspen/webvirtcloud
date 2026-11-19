from copy import copy

from computes.models import Compute
from computes.validators import validate_gstfsd_key
from drf_spectacular.utils import OpenApiParameter
from rest_framework import serializers
from vrtManager.connection import CONN_SOCKET, CONN_SSH, CONN_TCP, CONN_TLS


# a VM's or host's tags, by name: set on the web pages only
TAGS = {"many": True, "read_only": True, "slug_field": "name"}
TAG_PARAMETER = OpenApiParameter("tag", str, description="Only those with this tag")


def with_tag(queryset, request):
    """queryset's VMs or hosts with the ?tag= of request, all without one; their tags read at once."""
    tag = request.query_params.get("tag", "").strip().lower()  # the names are kept in lower case
    return (queryset.filter(tags__name=tag) if tag else queryset).prefetch_related("tags")


class ComputeSerializer(serializers.ModelSerializer):
    tags = serializers.SlugRelatedField(**TAGS)
    password = serializers.CharField(
        style={"input_type": "password"},
        write_only=True,
        trim_whitespace=False,
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

    def validate(self, attrs):
        # as the web form: the connection is tried and its host checked (Compute.clean)
        compute = copy(self.instance) if self.instance else Compute()
        for field, value in attrs.items():
            setattr(compute, field, value)
        compute.clean()
        return {**attrs, "host_uuid": compute.host_uuid}

    class Meta:
        model = Compute
        fields = ["id", "name", "hostname", "login", "password", "type", "details", "migration_address", "migration_tls",
                  "gstfsd_key", "tags"]
