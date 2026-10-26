import contextlib

from admin.permissions import IsSuperUser
from appsettings.settings import app_settings
from computes.models import Compute
from computes.utils import libvirt_compute_lock
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, inline_serializer
from libvirt import libvirtError
from logs.audit import audit, failed
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from vrtManager.storage import wvmStorage, wvmStorages
from webvirtcloud.serializers import StatusSerializer

from .serializers import StorageSerializer, StoragesSerializer, VolumeSerializer


class StorageViewSet(viewsets.ViewSet):
    """
    A viewset for listing retrieving storages.
    """

    permission_classes = [IsSuperUser]
    serializer_class = StoragesSerializer
    lookup_value_converter = "str"

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

    @extend_schema(responses=StorageSerializer)
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

    @extend_schema(request=None, responses=StatusSerializer)
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None, compute_pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, pk
        )
        with audit(request, compute, f"Storage pool {pk}", "start"):
            ret = conn.start()
        conn.close()
        return Response({"status": "Pool start command send: " + str(ret)})

    @extend_schema(request=None, responses=StatusSerializer)
    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None, compute_pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, pk
        )
        with audit(request, compute, f"Storage pool {pk}", "stop"):
            ret = conn.stop()
        conn.close()
        return Response({"status": "Pool stop command send: " + str(ret)})

    @extend_schema(request=None, responses=StatusSerializer)
    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None, compute_pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, pk
        )
        ret = conn.refresh()
        conn.close()
        return Response({"status": "Pool refresh command send: " + str(ret)})

    @extend_schema(
        request=None,
        responses=inline_serializer("PoolXML", {"return": serializers.CharField()}),
    )
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

    permission_classes = [IsSuperUser]
    serializer_class = VolumeSerializer
    lookup_value_converter = "str"

    def list(self, request, storage_pk=None, compute_pk=None):

        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, storage_pk
        )
        state = conn.is_active()

        if state:
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

    @extend_schema(responses={200: StatusSerializer, 400: dict, 409: StatusSerializer})
    def create(self, request, storage_pk=None, compute_pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, storage_pk
        )

        serializer = VolumeSerializer(data=request.data)
        if serializer.is_valid():
            subject, action = f"Storage pool {storage_pk}", f"add volume {serializer.validated_data['name']}"
            state = conn.is_active()
            if state:
                with contextlib.suppress(libvirtError):  # refused while a volume is cloned in the pool
                    conn.refresh()
                with audit(request, compute, subject, action) as entry:
                    ret = conn.create_volume(
                        serializer.validated_data["name"],
                        serializer.validated_data["size"],
                        serializer.validated_data["type"],
                        serializer.validated_data["meta_prealloc"],
                        int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID),
                        int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID),
                    )
                    entry.action = f"add volume {ret}"
                conn.close()
                return Response({"status": "Volume: " + ret + " is created"})
            else:
                failed(request, compute, subject, action, "pool is not active")
                return Response({"status": "Pool is not active"}, status=status.HTTP_409_CONFLICT)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(responses={200: StatusSerializer, 409: StatusSerializer})
    def destroy(self, request, storage_pk=None, compute_pk=None, pk=None):
        compute = get_object_or_404(Compute, pk=compute_pk)

        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, storage_pk
        )

        subject, action = f"Storage pool {storage_pk}", f"delete volume {pk}"
        if conn.is_active():
            # no VM operation attaches it between the check and the delete
            with audit(request, compute, subject, action), libvirt_compute_lock(compute):
                conn.del_volume(pk)
            conn.close()
            return Response({"status": "Volume: " + pk + " is deleted"})
        else:
            failed(request, compute, subject, action, "pool is not active")
            return Response({"status": "Pool is not active"}, status=status.HTTP_409_CONFLICT)
