import uuid

from django.conf import settings
from django.db import models

from computes.models import Compute
from instances.models import Instance
from operations.models import Operation
from vrtManager.backup import backup_prefix


class BackupTarget(models.Model):
    """Storage the backups go to: a pool on each compute that sees it."""

    name = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    checked_at = models.DateTimeField(null=True)  # its last target check that ended
    owners = models.BooleanField(default=False)  # VM owners with the backup permission may use it

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


class BackupPolicy(models.Model):
    """A schedule: its VMs (those chosen, or every VM of a compute) backed
    up into its target once a day at its time, the newest keep of each VM
    kept. Its jobs run as its owner, a superuser."""

    name = models.CharField(max_length=64, unique=True)
    target = models.ForeignKey(BackupTarget, on_delete=models.PROTECT, related_name="policies")
    compute = models.ForeignKey(Compute, on_delete=models.CASCADE, null=True, blank=True)
    instances = models.ManyToManyField(Instance, blank=True, related_name="backup_policies")
    time = models.TimeField()  # in the panel's time zone
    keep = models.PositiveSmallIntegerField()
    full_every = models.PositiveSmallIntegerField(default=1)  # a full backup every N; the others incremental
    frozen = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(keep__gte=1), name="policy_keeps_one")]

    def __str__(self):
        return self.name

    def vms(self):
        """Its VMs now: a compute's are those it has at this moment, templates left out."""
        if self.compute_id:
            return Instance.objects.filter(compute_id=self.compute_id, is_template=False).order_by("name")
        return self.instances.select_related("compute").order_by("name")


class BackupRun(models.Model):
    """A schedule's backup of one VM on one day: what it submitted, or why not."""

    SUBMITTED, SKIPPED, FAILED = "submitted", "skipped", "failed"
    STATES = [(SUBMITTED, "submitted"), (SKIPPED, "skipped"), (FAILED, "failed")]

    policy = models.ForeignKey(BackupPolicy, on_delete=models.CASCADE, related_name="runs")
    instance = models.ForeignKey(Instance, on_delete=models.CASCADE, related_name="backup_runs")
    day = models.DateField()  # the local day of the schedule's time
    state = models.CharField(max_length=16, choices=STATES)
    operation = models.ForeignKey(Operation, on_delete=models.SET_NULL, null=True)
    note = models.JSONField(default=list)  # messages (operations.utils.say), shown in the reader's language
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["policy", "instance", "day"], name="one_run_per_day")]


class Backup(models.Model):
    CREATING, READY, FAILED, DELETING, MISSING = "creating", "ready", "failed", "deleting", "missing"
    STATES = [(CREATING, "creating"), (READY, "ready"), (FAILED, "failed"), (DELETING, "deleting"), (MISSING, "missing")]
    LIVING = (CREATING, READY, MISSING, DELETING)  # its files are or will be in the target
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
    policy = models.ForeignKey(BackupPolicy, on_delete=models.SET_NULL, null=True, related_name="backups")
    # an incremental backup's base; its disk files have the parent's as backing files
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, related_name="children")
    checkpoint = models.CharField(max_length=64, blank=True)  # the VM's checkpoint made with it
    # whose job made it: a VM owner's own backups count in their backup quota
    taken_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    prefix = models.CharField(max_length=128)  # every file of the backup in the target begins with it and "-"

    class Meta:
        ordering = ["-created_at"]

    @property
    def being_made(self):
        """Its job still runs. One that ended uncertain (its host unreachable) leaves the row creating: it is
        deleted like a failed one."""
        return self.state == self.CREATING and self.operation_id is not None and self.operation.state in Operation.ACTIVE

    def depended_on(self):
        """Whether a backup builds on this one: a failed one holds nothing."""
        return self.children.filter(state__in=self.LIVING).exists()

    def save(self, *args, **kwargs):
        if not self.prefix:
            self.prefix = backup_prefix(self.vm_name, self.uuid)
        super().save(*args, **kwargs)


class BackupFile(models.Model):
    DISK, NVRAM, TPM, DOMAIN, MANIFEST = "disk", "nvram", "tpm", "domain", "manifest"
    ROLES = [(DISK, "disk"), (NVRAM, "nvram"), (TPM, "tpm"), (DOMAIN, "domain"), (MANIFEST, "manifest")]

    backup = models.ForeignKey(Backup, on_delete=models.CASCADE, related_name="files")
    role = models.CharField(max_length=16, choices=ROLES)
    dev = models.CharField(max_length=32, blank=True)  # a disk's target, a TPM state file's name
    volume = models.CharField(max_length=255)
    format = models.CharField(max_length=16, blank=True)
    capacity = models.BigIntegerField(default=0)
    size = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
