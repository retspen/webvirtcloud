from rest_framework import serializers

from computes.models import Compute
from instances.models import Instance
from operations.utils import words

from .models import Backup, BackupFile, BackupTarget


class BackupFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = BackupFile
        fields = ["role", "dev", "volume", "format", "capacity", "size", "sha256"]


class BackupSerializer(serializers.ModelSerializer):
    target = serializers.SlugRelatedField(slug_field="name", read_only=True)
    files = BackupFileSerializer(many=True, read_only=True)
    # what a verification found wrong with it or, else, with the first backup it builds on (a restore reads
    # those too); empty: nothing
    damage = serializers.SerializerMethodField()

    class Meta:
        model = Backup
        fields = ["uuid", "target", "instance", "vm_uuid", "vm_name", "compute_name", "created_at", "finished_at",
                  "state", "consistency", "size", "files", "operation", "verified_at", "damage"]
        read_only_fields = fields

    def get_damage(self, backup) -> str:
        damaged = backup.damaged_in_chain()
        return words(damaged.damage) if damaged else ""


class CreateBackupSerializer(serializers.Serializer):
    instance = serializers.PrimaryKeyRelatedField(queryset=Instance.objects.all())
    target = serializers.PrimaryKeyRelatedField(queryset=BackupTarget.objects.all())
    frozen = serializers.BooleanField(default=False)
    submission_key = serializers.CharField(write_only=True)


class SubmissionSerializer(serializers.Serializer):
    submission_key = serializers.CharField(write_only=True)


class RestoreDiskSerializer(serializers.Serializer):
    dev = serializers.CharField(max_length=32)
    compute = serializers.PrimaryKeyRelatedField(queryset=Compute.objects.all())
    pool = serializers.CharField(default="default")
    name = serializers.CharField(max_length=255)
    submission_key = serializers.CharField(write_only=True)


class RestoreBackupSerializer(serializers.Serializer):
    compute = serializers.PrimaryKeyRelatedField(queryset=Compute.objects.all())
    pool = serializers.CharField(default="default")
    name = serializers.CharField(max_length=64)
    connect = serializers.BooleanField(default=False)
    start = serializers.BooleanField(default=False)
    submission_key = serializers.CharField(write_only=True)
