"""A compute whose connection changes or that is deleted: its old connection
is not used again, and a VM listing of the old host is not saved."""

from unittest.mock import MagicMock, patch

from django.test import TestCase
from instances.models import Instance

from computes.models import Compute
from computes.tests.fakes import Domain
from computes.utils import refresh_instance_database


class ChangedConnectionTests(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="kvm1", hostname="192.0.2.1", login="wvc", password="old", type=1)

    @patch("computes.models.connection_manager")
    def test_the_old_connection_is_retired_on_a_change_and_a_delete(self, manager):
        self.compute.details = "rack 3"
        self.compute.save()
        manager.retire_connection.assert_not_called()  # the same connection
        self.compute.password = "new"
        self.compute.save()
        manager.retire_connection.assert_called_once_with("192.0.2.1", "wvc", "old", 1)
        self.compute.delete()
        manager.retire_connection.assert_called_with("192.0.2.1", "wvc", "new", 1)

    @patch("computes.models.wvmHostDetails")
    @patch("computes.models.connection_manager")
    def test_a_connection_checked_is_opened_anew(self, manager, host):
        manager.retire_connection.side_effect = lambda *args: host.assert_not_called()
        Compute(name="kvm2", hostname="192.0.2.2", login="wvc", password="pw", type=1).clean()
        manager.retire_connection.assert_called_once_with("192.0.2.2", "wvc", "pw", 1)
        host.assert_called_once()

    def test_a_listing_read_before_the_compute_changed_is_not_saved(self):
        proxy = MagicMock(**{"wvm.listAllDomains.return_value": [Domain("web-1", "11111111-1111-1111-1111-111111111111")]})
        self.compute.__dict__.update(proxy=proxy, status=True)
        Compute.objects.filter(pk=self.compute.pk).update(hostname="192.0.2.2")  # an edit meanwhile
        refresh_instance_database(self.compute)
        self.assertFalse(Instance.objects.exists())
