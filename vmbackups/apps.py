from django.apps import AppConfig
from django.db.models.signals import pre_delete


def keep_job_end(sender, instance, **kwargs):
    from .models import BackupRun

    BackupRun.keep_job_end(instance)


class VmbackupsConfig(AppConfig):
    name = "vmbackups"
    verbose_name = "Backups"

    def ready(self):
        # the job history drops ended jobs (operations.worker.housekeeping); a schedule's run keeps how its job went
        pre_delete.connect(keep_job_end, sender="operations.Operation")
