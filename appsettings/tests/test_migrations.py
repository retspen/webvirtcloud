"""The default settings rows of the first migrations carry fixed ids, which a
PostgreSQL id sequence does not see. A later migration that inserts without
an id must not collide with them."""

import importlib
import unittest
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.test import TestCase, TransactionTestCase

from appsettings.models import AppSettings

login_lockout = importlib.import_module("appsettings.migrations.0014_login_lockout_settings")


@unittest.skipUnless(connection.vendor == "postgresql", "id sequences are a PostgreSQL concern")
class SequenceAfterFixedIdsTestCase(TransactionTestCase):
    serialized_rollback = True

    def test_login_lockout_settings_insert_after_fixed_ids(self):
        with connection.schema_editor() as schema_editor:
            login_lockout.del_settings(apps, schema_editor)
            # the state after the fixed-id inserts: rows exist, the sequence starts at 1
            with connection.cursor() as cursor:
                cursor.execute("SELECT setval(pg_get_serial_sequence('appsettings_appsettings', 'id'), 1, false)")
            login_lockout.add_settings(apps, schema_editor)
        self.assertEqual(AppSettings.objects.filter(key__startswith="LOGIN_").count(), 2)


nic_type = importlib.import_module("appsettings.migrations.0016_nic_type_rtl8139")


class NicTypeTestCase(TestCase):
    def test_the_misspelt_nic_type_becomes_rtl8139(self):
        setting = AppSettings.objects.get(key="INSTANCE_NIC_DEFAULT_TYPE")
        self.assertEqual(setting.choices, "default,e1000,e1000e,rtl8139,virtio")
        AppSettings.objects.filter(pk=setting.pk).update(value="rt18139", choices="default,e1000,e1000e,rt18139,virtio")
        nic_type.fix_rtl8139(apps, SimpleNamespace(connection=connection))
        setting.refresh_from_db()
        self.assertEqual((setting.value, setting.choices), ("rtl8139", "default,e1000,e1000e,rtl8139,virtio"))


class SnapshotFreeSpaceSettingsTestCase(TestCase):
    def test_the_rows_fit_their_columns(self):
        # PostgreSQL refuses a value longer than the column, sqlite does not
        for key in ("SNAPSHOT_FREE_SPACE_PERCENT", "SNAPSHOT_FREE_SPACE_MIN_GIB"):
            setting = AppSettings.objects.get(key=key)
            for field in ("name", "key", "value", "description"):
                limit = AppSettings._meta.get_field(field).max_length
                if limit:
                    self.assertLessEqual(len(getattr(setting, field)), limit, f"{key} {field}")


class WorkerSettingsTestCase(TestCase):
    def test_the_rows_fit_their_columns(self):
        for key in ("WORKER_CONCURRENCY", "JOB_RETENTION_DAYS"):
            setting = AppSettings.objects.get(key=key)
            for field in ("name", "key", "value", "description"):
                limit = AppSettings._meta.get_field(field).max_length
                if limit:
                    self.assertLessEqual(len(getattr(setting, field)), limit, f"{key} {field}")


choices_fix = importlib.import_module("appsettings.migrations.0020_fix_setting_choices")


class ChoicesFixTestCase(TestCase):
    """Choices that offered values the panel cannot use, and a text setting
    that showed as a True/False list."""

    def test_the_broken_choices_are_fixed_and_their_values_moved(self):
        broken = {
            "CLONE_INSTANCE_DEFAULT_PREFIX": ("instance", "True,False"),
            "INSTANCE_VOLUME_DEFAULT_SCSI_CONTROLLER": ("virtio-blk", "virtio-scsi, lsilogic, virtio-blk"),
            "INSTANCE_MACHINE_DEFAULT_TYPE": ("x86_64", "q35,x86_64,virt"),
            "INSTANCE_CDROM_ADD": ("virtio", "None,ide,sata,scsi,virtio"),
        }
        for key, (value, choices) in broken.items():
            AppSettings.objects.filter(key=key).update(value=value, choices=choices)
        choices_fix.fix_choices(apps, SimpleNamespace(connection=connection))
        fixed = {s.key: (s.value, s.choices) for s in AppSettings.objects.filter(key__in=broken)}
        self.assertEqual(fixed, {
            "CLONE_INSTANCE_DEFAULT_PREFIX": ("instance", ""),
            "INSTANCE_VOLUME_DEFAULT_SCSI_CONTROLLER": ("virtio-scsi", "virtio-scsi,lsilogic"),
            "INSTANCE_MACHINE_DEFAULT_TYPE": ("q35", "q35,pc,virt"),
            "INSTANCE_CDROM_ADD": ("sata", "None,ide,sata,scsi"),
        })


descriptions = importlib.import_module("appsettings.migrations.0021_setting_descriptions")


class DescriptionsTestCase(TestCase):
    def test_every_setting_says_what_it_does_within_its_column(self):
        limit = AppSettings._meta.get_field("description").max_length
        for key, text in descriptions.DESCRIPTIONS.items():
            with self.subTest(key=key):
                self.assertLessEqual(len(text), limit)
                self.assertEqual(AppSettings.objects.get(key=key).description, text)
