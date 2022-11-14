from computes.models import Compute
from rest_framework import permissions, viewsets
from rest_framework.response import Response
from vrtManager.create import wvmCreate

from .serializers import ComputeSerializer


class ComputeViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows computes to be viewed or edited.
    """

    queryset = Compute.objects.all().order_by("name")
    serializer_class = ComputeSerializer
    permission_classes = [permissions.IsAuthenticated]


class ComputeArchitecturesView(viewsets.ViewSet):
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
