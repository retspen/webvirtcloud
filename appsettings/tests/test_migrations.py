"""The settings rows: those a new database gets fit their columns (PostgreSQL
refuses a longer value, SQLite does not), say what they do, and hold one of
their choices. The steps the squashed migration replaces still run on an
installation that stopped between them: they repair its rows, and their
inserts do not collide with the fixed ids of the first ones."""

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
vnc_and_nic = importlib.import_module("appsettings.migrations.0025_vnc_console_and_nic_descriptions")


class DescriptionsTestCase(TestCase):
    def test_every_setting_says_what_it_does_within_its_column(self):
        limit = AppSettings._meta.get_field("description").max_length
        removed = {"VIEW_INSTANCE_DETAIL_BOTTOM_BAR"}  # by 0023
        # as the last migration that describes a setting says
        for key, text in {**descriptions.DESCRIPTIONS, **vnc_and_nic.DESCRIPTIONS}.items():
            with self.subTest(key=key):
                self.assertLessEqual(len(text), limit)
                if key not in removed:
                    self.assertEqual(AppSettings.objects.get(key=key).description, text)
        self.assertFalse(AppSettings.objects.filter(key__in=removed).exists())


cpu_mode = importlib.import_module("appsettings.migrations.0022_cpu_mode_choices")


class CpuModeChoicesTestCase(TestCase):
    def test_the_default_cpu_mode_is_one_the_new_vm_dialog_offers(self):
        for old, new in (("no-model", "host-model"), ("custom", "host-model"), ("host-passthrough", "host-passthrough")):
            with self.subTest(old=old):
                AppSettings.objects.filter(key="INSTANCE_CPU_DEFAULT_MODE").update(
                    value=old, choices="no-model,host-model,host-passthrough,custom")
                cpu_mode.fix_cpu_mode(apps, SimpleNamespace(connection=connection))
                setting = AppSettings.objects.get(key="INSTANCE_CPU_DEFAULT_MODE")
                self.assertEqual((setting.value, setting.choices), (new, "host-model,host-passthrough,maximum"))


class SettingsRowsTestCase(TestCase):
    def test_every_row_fits_its_columns_and_has_a_description(self):
        for setting in AppSettings.objects.all():
            with self.subTest(key=setting.key):
                self.assertTrue(setting.description)
                for field in ("name", "key", "value", "choices", "description"):
                    limit = AppSettings._meta.get_field(field).max_length
                    self.assertLessEqual(len(getattr(setting, field)), limit, field)

    def test_a_setting_with_choices_holds_one_of_them(self):
        for setting in AppSettings.objects.exclude(choices=""):
            with self.subTest(key=setting.key):
                self.assertIn(setting.value, setting.choices_as_list())

    def test_the_choices_offer_only_what_the_panel_uses(self):
        rows = {s.key: (s.value, s.choices) for s in AppSettings.objects.all()}
        self.assertEqual(rows["INSTANCE_NIC_DEFAULT_TYPE"][1], "default,e1000,e1000e,rtl8139,virtio")
        self.assertEqual(rows["INSTANCE_CPU_DEFAULT_MODE"], ("host-model", "host-model,host-passthrough,maximum"))
        self.assertEqual(rows["INSTANCE_MACHINE_DEFAULT_TYPE"], ("q35", "q35,pc,virt"))
        self.assertEqual(rows["INSTANCE_CDROM_ADD"], ("sata", "None,ide,sata,scsi"))
        self.assertEqual(rows["CLONE_INSTANCE_DEFAULT_PREFIX"][1], "")
