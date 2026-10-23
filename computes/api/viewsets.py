from admin.permissions import IsSuperUser
from computes.models import Compute
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from logs.audit import audit, changed_fields, snapshot
from rest_framework import viewsets
from rest_framework.response import Response
from vrtManager.create import wvmCreate

from .serializers import ComputeSerializer


class ComputeViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows computes to be viewed or edited.
    """

    queryset = Compute.objects.all().order_by("name")
    lookup_value_converter = "int"
    serializer_class = ComputeSerializer
    permission_classes = [IsSuperUser]

    def perform_create(self, serializer):
        data = serializer.validated_data
        with audit(self.request, data["name"], f"Compute {data['name']} ({data['hostname']})", "add"):
            serializer.save()

    def perform_update(self, serializer):
        compute = serializer.instance
        subject = f"Compute {compute.name} ({compute.hostname})"
        before = snapshot(compute)
        with audit(self.request, compute, subject, "change") as entry:
            serializer.save()
            fields = changed_fields(before, snapshot(compute))
            entry.action = "change " + ", ".join(fields)
            entry.skip = not fields

    def perform_destroy(self, instance):
        with audit(self.request, instance, f"Compute {instance.name} ({instance.hostname})", "delete"):
            instance.delete()


class ComputeArchitecturesView(viewsets.ViewSet):
    permission_classes = [IsSuperUser]

    # The list is a mapping of architecture -> machine types, not an array,
    # so drf-spectacular would name it "retrieve" and clash with retrieve().
    @extend_schema(operation_id="api_v1_computes_archs_list", responses=OpenApiTypes.OBJECT)
    def list(self, request, compute_pk=None):
        """
        Return a list of supported host architectures.
        """
        compute = Compute.objects.get(pk=compute_pk)
        conn = wvmCreate(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
        )
        return Response(conn.get_hypervisors_machines())

    @extend_schema(responses={200: {"type": "array", "items": {"type": "string"}}})
    def retrieve(self, request, compute_pk=None, pk=None):
        compute = Compute.objects.get(pk=compute_pk)
        conn = wvmCreate(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
        )
        return Response(conn.get_machine_types(pk))


class ComputeMachinesView(viewsets.ViewSet):
    permission_classes = [IsSuperUser]

    def list(self, request, compute_pk=None, archs_pk=None):
        """
        Return a list of supported host architectures.
        """
        compute = Compute.objects.get(pk=compute_pk)
        conn = wvmCreate(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
        )
        return Response(conn.get_machine_types(archs_pk))
