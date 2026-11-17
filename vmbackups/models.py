import uuid

from django.db import models

from computes.models import Compute
from instances.models import Instance
from operations.models import Operation


class BackupTarget(models.Model):
    """Storage the backups go to: a pool on each compute that sees it."""

    name = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def pool_on(self, compute):
        return self.pools.filter(compute=compute).first()


class BackupTargetPool(models.Model):
    """The target's pool on one compute; its UUID is checked before each use,
    so a pool replaced by another of the same name is refused. A removed
    compute takes its pool row with it: the backups stay in the target."""

    target = models.ForeignKey(BackupTarget, on_delete=models.CASCADE, related_name="pools")
    compute = models.ForeignKey(Compute, on_delete=models.CASCADE)
    pool = models.CharField(max_length=128)
    pool_uuid = models.CharField(max_length=36)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["target", "compute"], name="one_pool_per_target_and_compute")]


class Backup(models.Model):
    CREATING, READY, FAILED, DELETING = "creating", "ready", "failed", "deleting"
    STATES = [(CREATING, "creating"), (READY, "ready"), (FAILED, "failed"), (DELETING, "deleting")]
    OFFLINE, FROZEN, CRASH = "offline", "frozen", "crash"
    CONSISTENCIES = [(OFFLINE, "offline"), (FROZEN, "frozen"), (CRASH, "crash-consistent")]

    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    target = models.ForeignKey(BackupTarget, on_delete=models.PROTECT, related_name="backups")
    instance = models.ForeignKey(Instance, on_delete=models.SET_NULL, null=True, related_name="backups")
    # kept when the VM row is gone
    vm_uuid = models.CharField(max_length=36)
    vm_name = models.CharField(max_length=255)
    compute_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    state = models.CharField(max_length=16, choices=STATES, default=CREATING)
    consistency = models.CharField(max_length=16, choices=CONSISTENCIES, blank=True)
    size = models.BigIntegerField(default=0)  # bytes in the target
    manifest = models.JSONField(default=dict)
    operation = models.ForeignKey(Operation, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def prefix(self):
        """Every file of the backup in the target is named from its UUID only."""
        return f"wvc-{self.uuid}"


class BackupFile(models.Model):
    DISK, NVRAM, DOMAIN, MANIFEST = "disk", "nvram", "domain", "manifest"
    ROLES = [(DISK, "disk"), (NVRAM, "nvram"), (DOMAIN, "domain"), (MANIFEST, "manifest")]

    backup = models.ForeignKey(Backup, on_delete=models.CASCADE, related_name="files")
    role = models.CharField(max_length=16, choices=ROLES)
    dev = models.CharField(max_length=32, blank=True)
    volume = models.CharField(max_length=255)
    format = models.CharField(max_length=16, blank=True)
    capacity = models.BigIntegerField(default=0)
    size = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
