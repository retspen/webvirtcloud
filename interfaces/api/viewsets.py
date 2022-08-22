from django.shortcuts import get_object_or_404
from computes.models import Compute
from rest_framework import status, viewsets


from vrtManager.interface import wvmInterfaces, wvmInterface

from .serializers import InterfacesSerializer
from rest_framework.response import Response



class InterfaceViewSet(viewsets.ViewSet):
    """
    A viewset for listing retrieving interfaces.
    """
    
    def list(self, request, compute_pk=None):
        queryset = []
        compute = get_object_or_404(Compute, pk=compute_pk)
        
        conn = wvmInterfaces(compute.hostname, compute.login, compute.password, compute.type)
        ifaces = conn.get_ifaces()

        for iface in ifaces:
            interf = wvmInterface(compute.hostname, compute.login, compute.password, compute.type, iface)
            queryset.append(interf.get_details())

        serializer = InterfacesSerializer(queryset, many=True, context={'request': request})

        return Response(serializer.data)
        
