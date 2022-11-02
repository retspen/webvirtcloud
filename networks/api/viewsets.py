from computes.models import Compute
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.response import Response
from vrtManager.network import wvmNetworks

from .serializers import NetworksSerializer


class NetworkViewSet(viewsets.ViewSet):
    """
    A viewset for listing retrieving networks.
    """

    def list(self, request, compute_pk=None):

        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmNetworks(
            compute.hostname, compute.login, compute.password, compute.type
        )
        queryset = conn.get_networks_info()

        serializer = NetworksSerializer(
            queryset, many=True, context={"request": request}
        )

        return Response(serializer.data)
