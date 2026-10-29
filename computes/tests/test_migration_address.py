"""A compute's migration address: where other hosts send a migrating VM's
memory. Empty means libvirt's default (the destination's own hostname)."""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from computes.models import Compute
from computes.validators import validate_migration_address
from instances.models import Instance
from instances.utils import migrate_instance


class MigrationAddressTests(TestCase):
    def test_accepted_and_refused_values(self):
        for value in ("192.0.2.12", "kvm102.example.org", "kvm-102", "2001:db8::12",
                      "kvm102.example.org."):
            with self.subTest(value=value):
                validate_migration_address(value)
        for value in ("tcp://10.0.0.1", "10.0.0.1:49152", "[2001:db8::12]", "host name", "-bad", "a..b", "10.0.0.1/24", "x;y",
                      "2001:db8::12%eth0", "2001:db8::12%bad]:49152", "a.."):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_migration_address(value)

    def test_migration_uri(self):
        cases = {"": None, "192.0.2.12": "tcp://192.0.2.12", "kvm102.example.org": "tcp://kvm102.example.org",
                 "2001:db8::12": "tcp://[2001:db8::12]"}
        for address, uri in cases.items():
            with self.subTest(address=address):
                self.assertEqual(Compute(migration_address=address).migration_uri, uri)

    def test_the_compute_form_saves_it(self):
        self.client.force_login(get_user_model().objects.create_superuser("ma-admin", "ma@example.com", "pw"))
        compute = Compute.objects.create(name="ma", hostname="10.0.0.9", login="root", password="", type=2)
        data = {"name": "ma", "hostname": "10.0.0.9", "login": "root", "type": 2, "details": "", "migration_address": "198.51.100.9"}
        self.client.post(reverse("compute_update", args=[compute.id]), data)
        compute.refresh_from_db()
        self.assertEqual(compute.migration_address, "198.51.100.9")
        self.client.post(reverse("compute_update", args=[compute.id]), {**data, "migration_address": "tcp://x"})
        compute.refresh_from_db()
        self.assertEqual(compute.migration_address, "198.51.100.9")

    def test_a_migration_uses_the_destination_address(self):
        source = Compute.objects.create(name="ma-src", hostname="10.0.0.8", login="root", password="", type=2)
        dest = Compute.objects.create(name="ma-dst", hostname="kvm9", login="root", password="", type=2,
                                      migration_address="198.51.100.9")
        vm = Instance.objects.create(compute=source, name="vm", uuid="u-ma")
        user = get_user_model().objects.create_superuser("ma-mig", "mm@example.com", "pw")
        with patch.object(Compute, "status", True), \
             patch("instances.utils.wvmInstances") as instances, \
             patch("instances.utils.wvmInstance"), \
             patch.object(Instance, "proxy", MagicMock()):
            instances.return_value.moveto.return_value = ("live", [])
            migrate_instance(dest, vm, user, live=True)
        self.assertEqual(instances.return_value.moveto.call_args.kwargs["uri"], "tcp://198.51.100.9")
