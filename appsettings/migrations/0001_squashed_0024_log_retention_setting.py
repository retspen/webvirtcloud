"""The settings table and its rows as migrations 0001 to 0024 left them,
which this migration replaces."""

from django.db import migrations, models

# (name, key, value, choices, description) of each setting, in their old order
SETTINGS = [
    ('Theme', 'BOOTSTRAP_THEME', 'zephyr', '',
     'Bootstrap CSS & Bootswatch Theme'),
    ('All Instances View Style', 'VIEW_INSTANCES_LIST_STYLE', 'grouped', 'grouped,nongrouped',
     'Instances page for administrators: VMs under their host, or one list'),
    ('Logs per Page', 'LOGS_PER_PAGE', '100', '',
     'Rows per page on the Logs page'),
    ('Multiple Owner for VM', 'ALLOW_INSTANCE_MULTIPLE_OWNER', 'True', 'True,False',
     'A VM can be given to more than one user'),
    ('Quota Debug', 'QUOTA_DEBUG', 'True', 'True,False',
     'A quota refusal shows the numbers: what would be used and what is allowed'),
    ('Disk Format', 'INSTANCE_VOLUME_DEFAULT_FORMAT', 'qcow2', 'raw,qcow,qcow2',
     'Format of new disk images in directory pools'),
    ('Disk Bus', 'INSTANCE_VOLUME_DEFAULT_BUS', 'virtio', 'virtio,scsi,ide,usb,sata',
     'Bus of new disks'),
    ('Disk SCSI Controller', 'INSTANCE_VOLUME_DEFAULT_SCSI_CONTROLLER', 'virtio-scsi', 'virtio-scsi,lsilogic',
     'Controller model for disks on the SCSI bus'),
    ('Disk Cache', 'INSTANCE_VOLUME_DEFAULT_CACHE', 'directsync', 'default,directsync,none,unsafe,writeback,writethrough',
     'Cache mode of new disks'),
    ('Disk IO Type', 'INSTANCE_VOLUME_DEFAULT_IO', 'default', 'default,native,threads',
     'I/O mode of new disks (native needs cache none or directsync)'),
    ('Disk Detect Zeroes', 'INSTANCE_VOLUME_DEFAULT_DETECT_ZEROES', 'default', 'default,on,off,unmap',
     'Detect zeroes of new disks: how blocks of zeros the guest writes are stored'),
    ('Disk Discard', 'INSTANCE_VOLUME_DEFAULT_DISCARD', 'default', 'default,unmap,ignore',
     "Discard of new disks (unmap: the guest's TRIM frees space in the image)"),
    ('Disk Owner UID', 'INSTANCE_VOLUME_DEFAULT_OWNER_UID', '0', '',
     'Owner of new disk image files (0: root; qemu is often 107)'),
    ('Disk Owner GID', 'INSTANCE_VOLUME_DEFAULT_OWNER_GID', '0', '',
     'Group of new disk image files (0: root; qemu is often 107)'),
    ('VM CPU Mode', 'INSTANCE_CPU_DEFAULT_MODE', 'host-model', 'host-model,host-passthrough,maximum',
     'CPU mode chosen first for a new VM'),
    ('VM Machine Type', 'INSTANCE_MACHINE_DEFAULT_TYPE', 'q35', 'q35,pc,virt',
     'Machine type chosen first on the new VM pages'),
    ('VM Firmware Type', 'INSTANCE_FIRMWARE_DEFAULT_TYPE', 'BIOS', 'BIOS,UEFI',
     'Firmware chosen first for a new x86_64 VM'),
    ('VM Architecture Type', 'INSTANCE_ARCH_DEFAULT_TYPE', 'x86_64', 'x86_64,i686,aarch64',
     'Architecture chosen first on the new VM pages'),
    ('VM Clone Name Prefix', 'CLONE_INSTANCE_DEFAULT_PREFIX', 'instance', '',
     'Prefix of the names made for clones: prefix1, prefix2, ...'),
    ('VM Clone Auto Name', 'CLONE_INSTANCE_AUTO_NAME', 'False', 'True,False',
     'Users who are not administrators get clone names made from the prefix'),
    ('Show Access Root Pass', 'SHOW_ACCESS_ROOT_PASSWORD', 'False', 'True,False',
     "Show Root Password on a VM's Access tab"),
    ('Show Access SSH Keys', 'SHOW_ACCESS_SSH_KEYS', 'False', 'True,False',
     "Show SSH Keys on a VM's Access tab"),
    ('Console Scale', 'CONSOLE_SCALE', 'False', 'True,False',
     'The console starts scaled to its window'),
    ('Console View-Only', 'CONSOLE_VIEW_ONLY', 'False', 'True,False',
     'The console starts view-only: no keyboard or mouse input'),
    ('Console Resize Session', 'CONSOLE_RESIZE_SESSION', 'False', 'True,False',
     'The console starts asking the guest to fit its screen to the window'),
    ('Console Clip Viewport', 'CONSOLE_CLIP_VIEWPORT', 'False', 'True,False',
     'The console starts clipped to its window, without scaling'),
    ('VM DRBD Status', 'VM_DRBD_STATUS', 'False', 'True,False',
     "The Instances page shows each VM's DRBD state"),
    ('VM CD-ROM Device', 'INSTANCE_CDROM_ADD', 'sata', 'None,ide,sata,scsi',
     'Bus of the CD-ROM a new VM gets (None: no CD-ROM)'),
    ('VM Video Type', 'INSTANCE_VIDEO_DEFAULT_TYPE', 'vga', 'None,virtio,vga,cirrus,vmvga,bochs,ramfb',
     'Video device chosen first for a new VM'),
    ('VM Input Device', 'INSTANCE_INPUT_DEFAULT_DEVICE', 'default', 'None,default,virtio,usb',
     'Input device chosen first for a new VM (None: no input device)'),
    ('VM NIC Type', 'INSTANCE_NIC_DEFAULT_TYPE', 'default', 'default,e1000,e1000e,rtl8139,virtio',
     "Network card model chosen first for a new VM (default: libvirt's choice)"),
    ('Login Failure Limit', 'LOGIN_FAILURE_LIMIT', '5', '',
     'Failed logins of a user from one address before it is locked'),
    ('Login Lockout Minutes', 'LOGIN_LOCKOUT_MINUTES', '15', '',
     'How long a locked login stays locked, in minutes'),
    ('Snapshot Free Percent', 'SNAPSHOT_FREE_SPACE_PERCENT', '10', '',
     "Free space a storage pool keeps for a snapshot, in percent of the VM's disks in it (0: none)"),
    ('Snapshot Free Min GiB', 'SNAPSHOT_FREE_SPACE_MIN_GIB', '1', '',
     'Free space a storage pool keeps for a snapshot at least, in GiB (0: none)'),
    ('Worker Concurrency', 'WORKER_CONCURRENCY', '4', '',
     'Jobs the worker runs at the same time (1-16)'),
    ('Job Retention Days', 'JOB_RETENTION_DAYS', '30', '',
     'Days finished jobs stay in the job history (1-3650)'),
    ('Log Retention Days', 'LOG_RETENTION_DAYS', '365', '',
     'Days the Logs page keeps its rows (1-3650)'),
]


def add_settings(apps, schema_editor):
    AppSettings = apps.get_model("appsettings", "AppSettings")
    AppSettings.objects.using(schema_editor.connection.alias).bulk_create(
        AppSettings(name=name, key=key, value=value, choices=choices, description=description)
        for name, key, value, choices, description in SETTINGS
    )


class Migration(migrations.Migration):

    replaces = [
        ("appsettings", "0001_initial"),
        ("appsettings", "0002_auto_20200527_1603"),
        ("appsettings", "0003_auto_20200615_0637"),
        ("appsettings", "0004_auto_20200716_0637"),
        ("appsettings", "0005_auto_20200911_1233"),
        ("appsettings", "0006_auto_20220630_0717"),
        ("appsettings", "0007_auto_20220905_0918"),
        ("appsettings", "0008_auto_20220905_1459"),
        ("appsettings", "0009_alter_appsettings_id"),
        ("appsettings", "0010_auto_20231030_1305"),
        ("appsettings", "0011_alter_appsettings_id"),
        ("appsettings", "0012_remove_spice_qemu_console_type"),
        ("appsettings", "0013_remove_qemu_console_default_type"),
        ("appsettings", "0014_login_lockout_settings"),
        ("appsettings", "0015_remove_clone_instance_auto_migrate"),
        ("appsettings", "0016_nic_type_rtl8139"),
        ("appsettings", "0017_snapshot_free_space_settings"),
        ("appsettings", "0018_worker_settings"),
        ("appsettings", "0019_prebuilt_themes"),
        ("appsettings", "0020_fix_setting_choices"),
        ("appsettings", "0021_setting_descriptions"),
        ("appsettings", "0022_cpu_mode_choices"),
        ("appsettings", "0023_remove_bottom_bar"),
        ("appsettings", "0024_log_retention_setting"),
    ]

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AppSettings",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=25, verbose_name="name")),
                ("key", models.CharField(db_index=True, max_length=50, unique=True, verbose_name="key")),
                ("value", models.CharField(max_length=25, verbose_name="value")),
                ("choices", models.CharField(max_length=70, verbose_name="choices")),
                ("description", models.CharField(max_length=100, null=True, verbose_name="description")),
            ],
        ),
        migrations.RunPython(add_settings, migrations.RunPython.noop),
    ]
