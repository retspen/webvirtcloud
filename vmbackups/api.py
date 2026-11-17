from django.urls import reverse
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from admin.permissions import IsSuperUser
from operations import jobs
from operations.api.serializers import OperationSerializer
from webvirtcloud.serializers import ErrorSerializer

from .models import Backup
from .serializers import (BackupSerializer, CreateBackupSerializer, RestoreBackupSerializer, RestoreDiskSerializer,
                          SubmissionSerializer)


def _accepted(request, op):
    return Response(OperationSerializer(op, context={"request": request}).data, status=status.HTTP_202_ACCEPTED,
                    headers={"Location": reverse("operation-detail", args=[op.pk])})


class BackupViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """VM backups: list, read, back a VM up and delete a backup (jobs,
    answered 202)."""

    permission_classes = [IsSuperUser]
    serializer_class = BackupSerializer
    queryset = Backup.objects.select_related("target").prefetch_related("files")
    lookup_field = "uuid"

    @extend_schema(request=CreateBackupSerializer, responses={202: OperationSerializer, 400: dict, 409: ErrorSerializer})
    def create(self, request):
        serializer = CreateBackupSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        raw = {"instance": data["instance"].pk, "target": data["target"].pk, "frozen": data["frozen"]}
        return _accepted(request, jobs.submit("backup.create", request.user, raw, data["submission_key"]))

    @extend_schema(request=SubmissionSerializer, responses={202: OperationSerializer, 409: ErrorSerializer})
    def destroy(self, request, uuid=None):
        backup = self.get_object()
        serializer = SubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key = serializer.validated_data["submission_key"]
        return _accepted(request, jobs.submit("backup.delete", request.user, {"backup": str(backup.uuid)}, key))

    @extend_schema(request=RestoreBackupSerializer, responses={202: OperationSerializer, 400: dict, 409: ErrorSerializer})
    @action(detail=True, methods=["post"])
    def restore(self, request, uuid=None):
        backup = self.get_object()
        serializer = RestoreBackupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        key = data.pop("submission_key")
        raw = {**data, "backup": str(backup.uuid), "compute": data["compute"].pk}
        return _accepted(request, jobs.submit("backup.restore", request.user, raw, key))

    @extend_schema(request=SubmissionSerializer, responses={202: OperationSerializer, 409: ErrorSerializer})
    @action(detail=True, methods=["post"], url_path="restore-over")
    def restore_over(self, request, uuid=None):
        backup = self.get_object()
        serializer = SubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key = serializer.validated_data["submission_key"]
        return _accepted(request, jobs.submit("backup.restore_over", request.user, {"backup": str(backup.uuid)}, key))

    @extend_schema(request=RestoreDiskSerializer, responses={202: OperationSerializer, 400: dict, 409: ErrorSerializer})
    @action(detail=True, methods=["post"], url_path="restore-disk")
    def restore_disk(self, request, uuid=None):
        backup = self.get_object()
        serializer = RestoreDiskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        key = data.pop("submission_key")
        raw = {**data, "backup": str(backup.uuid), "compute": data["compute"].pk}
        return _accepted(request, jobs.submit("backup.restore_disk", request.user, raw, key))
