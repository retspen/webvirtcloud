from django.shortcuts import reverse
from django.test import TestCase

from .models import Compute


class ComputesTestCase(TestCase):
    def setUp(self):
        self.client.login(username='admin', password='admin')
        Compute(
            name='local',
            hostname='localhost',
            login='',
            password='',
            details='local',
            type=4,
        ).save()

    def test_index(self):
        response = self.client.get(reverse('computes'))
        self.assertEqual(response.status_code, 200)

    def test_overview(self):
        response = self.client.get(reverse('overview', args=[1]))
        self.assertEqual(response.status_code, 200)

    def test_graph(self):
        response = self.client.get(reverse('compute_graph', args=[1]))
        self.assertEqual(response.status_code, 200)

    def test_instances(self):
        response = self.client.get(reverse('instances', args=[1]))
        self.assertEqual(response.status_code, 200)

    def test_storages(self):
        response = self.client.get(reverse('storages', args=[1]))
        self.assertEqual(response.status_code, 200)

    def test_default_storage_volumes(self):
        response = self.client.get(reverse('volumes', kwargs={'compute_id': 1, 'pool': 'default'}))
        self.assertEqual(response.status_code, 200)

    def test_default_storage(self):
        response = self.client.get(reverse('storage', kwargs={'compute_id': 1, 'pool': 'default'}))
        self.assertEqual(response.status_code, 200)

    def test_networks(self):
        response = self.client.get(reverse('networks', args=[1]))
        self.assertEqual(response.status_code, 200)

    def test_default_network(self):
        response = self.client.get(reverse('network', kwargs={'compute_id': 1, 'pool': 'default'}))
        self.assertEqual(response.status_code, 200)

    def test_interfaces(self):
        response = self.client.get(reverse('interfaces', args=[1]))
        self.assertEqual(response.status_code, 200)

    # TODO: add test for single interface

    def test_nwfilters(self):
        response = self.client.get(reverse('nwfilters', args=[1]))
        self.assertEqual(response.status_code, 200)

    # TODO: add test for single nwfilter

    def test_secrets(self):
        response = self.client.get(reverse('secrets', args=[1]))
        self.assertEqual(response.status_code, 200)

    def test_create_instance_select_type(self):
        response = self.client.get(reverse('create_instance_select_type', args=[1]))
        self.assertEqual(response.status_code, 200)

    # TODO: create_instance

    def test_machines(self):
        response = self.client.get(reverse('machines', kwargs={'compute_id': 1, 'arch': 'x86_64'}))
        self.assertEqual(response.status_code, 200)

    # TODO: get_compute_disk_buses

    # TODO: domcaps
