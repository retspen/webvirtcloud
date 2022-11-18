from appsettings.settings import app_settings
from computes.models import Compute
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from vrtManager.storage import wvmStorage, wvmStorages

from .serializers import StorageSerializer, StoragesSerializer, VolumeSerializer


class StorageViewSet(viewsets.ViewSet):
    """
    A viewset for listing retrieving storages.
    """

    def list(self, request, compute_pk=None):

        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorages(
            compute.hostname, compute.login, compute.password, compute.type
        )
        queryset = conn.get_storages_info()

        serializer = StoragesSerializer(
            queryset, many=True, context={"request": request}
        )

        return Response(serializer.data)

    def retrieve(self, request, pk=None, compute_pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, pk
        )

        infoset = {
            "state": conn.is_active(),
            "size": conn.get_size()[0],
            "free": conn.get_size()[1],
            "status": conn.get_status(),
            "path": conn.get_target_path(),
            "type": conn.get_type(),
            "autostart": conn.get_autostart(),
            "volumes": conn.update_volumes(),
        }

        serializer = StorageSerializer(
            infoset, many=False, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None, compute_pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, pk
        )
        ret = conn.start()
        conn.close()
        return Response({"status": "Pool start command send: " + str(ret)})

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None, compute_pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, pk
        )
        ret = conn.stop()
        conn.close()
        return Response({"status": "Pool stop command send: " + str(ret)})

    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None, compute_pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, pk
        )
        ret = conn.refresh()
        conn.close()
        return Response({"status": "Pool refresh command send: " + str(ret)})

    @action(detail=True, methods=["post"])
    def XML_description(self, request, pk=None, compute_pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, pk
        )
        ret = conn._XMLDesc(0)
        conn.close()
        return Response({"return": str(ret)})


class VolumeViewSet(viewsets.ViewSet):

    """
    A simple ViewSet for listing or retrieving Storage Volumes.
    """

    serializer_class = VolumeSerializer
    lookup_value_regex = "[^/]+"

    def list(self, request, storage_pk=None, compute_pk=None):

        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, storage_pk
        )
        state = conn.is_active()

        if state:
            conn.refresh()
            volume_queryset = conn.update_volumes()
        else:
            volume_queryset = None
        conn.close()
        serializer = VolumeSerializer(
            volume_queryset, many=True, context={"request": request}
        )

        return Response(serializer.data)

    def retrieve(self, request, storage_pk=None, compute_pk=None, pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, storage_pk
        )
        state = conn.is_active()

        volume_queryset = conn.get_volume_details(pk) if state else None
        conn.close()
        serializer = VolumeSerializer(
            volume_queryset, many=False, context={"request": request}
        )

        return Response(serializer.data)

    def create(self, request, storage_pk=None, compute_pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, storage_pk
        )

        serializer = VolumeSerializer(data=request.data)
        if serializer.is_valid():
            state = conn.is_active()
            if state:
                conn.refresh()
                ret = conn.create_volume(
                    serializer.validated_data["name"],
                    serializer.validated_data["size"],
                    serializer.validated_data["type"],
                    serializer.validated_data["meta_prealloc"],
                    int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID),
                    int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID),
                )
                conn.close()
                return Response({"status": "Volume: " + ret + " is created"})
            else:
                return Response({"status": "Pool is not active"})
        else:
            return Response({"status": "Data is not right for create volume"})

    def destroy(self, request, storage_pk=None, compute_pk=None, pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, storage_pk
        )

        if conn.is_active():
            conn.del_volume(pk)
            conn.close()
            return Response({"status": "Volume: " + pk + " is deleted"})
        else:
            return Response({"status": "Pool is not active"})
