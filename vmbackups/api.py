from django.urls import reverse
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from admin.permissions import IsSuperUser
from operations import jobs
from operations.api.serializers import OperationSerializer
from webvirtcloud.serializers import ErrorSerializer

from .models import Backup
from .serializers import BackupSerializer, CreateBackupSerializer


class BackupViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """VM backups: list, read, and back a VM up (a job, answered 202)."""

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
        op = jobs.submit("backup.create", request.user, raw, data["submission_key"])
        return Response(OperationSerializer(op, context={"request": request}).data, status=status.HTTP_202_ACCEPTED,
                        headers={"Location": reverse("operation-detail", args=[op.pk])})
