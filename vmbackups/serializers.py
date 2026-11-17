from rest_framework import serializers

from computes.models import Compute
from instances.models import Instance

from .models import Backup, BackupFile, BackupTarget


class BackupFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = BackupFile
        fields = ["role", "dev", "volume", "format", "capacity", "size", "sha256"]


class BackupSerializer(serializers.ModelSerializer):
    target = serializers.SlugRelatedField(slug_field="name", read_only=True)
    files = BackupFileSerializer(many=True, read_only=True)

    class Meta:
        model = Backup
        fields = ["uuid", "target", "instance", "vm_uuid", "vm_name", "compute_name", "created_at", "finished_at",
                  "state", "consistency", "size", "files", "operation"]
        read_only_fields = fields


class CreateBackupSerializer(serializers.Serializer):
    instance = serializers.PrimaryKeyRelatedField(queryset=Instance.objects.all())
    target = serializers.PrimaryKeyRelatedField(queryset=BackupTarget.objects.all())
    frozen = serializers.BooleanField(default=False)
    submission_key = serializers.CharField(write_only=True)


class SubmissionSerializer(serializers.Serializer):
    submission_key = serializers.CharField(write_only=True)


class RestoreBackupSerializer(serializers.Serializer):
    compute = serializers.PrimaryKeyRelatedField(queryset=Compute.objects.all())
    pool = serializers.CharField(default="default")
    name = serializers.CharField(max_length=64)
    connect = serializers.BooleanField(default=False)
    start = serializers.BooleanField(default=False)
    submission_key = serializers.CharField(write_only=True)
