from admin.permissions import IsSuperUser
from django.shortcuts import get_object_or_404
from computes.models import Compute
from rest_framework import viewsets
from rest_framework.response import Response
from vrtManager.interface import wvmInterfaces

from .serializers import InterfacesSerializer


class InterfaceViewSet(viewsets.ViewSet):
    """
    A viewset for listing retrieving interfaces.
    """

    permission_classes = [IsSuperUser]
    serializer_class = InterfacesSerializer
    
    def list(self, request, compute_pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)
        
        conn = wvmInterfaces(compute.hostname, compute.login, compute.password, compute.type)
        queryset = conn.get_ifaces_info()

        serializer = InterfacesSerializer(queryset, many=True, context={'request': request})

        return Response(serializer.data)
        
