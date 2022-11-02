from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import reverse
from django.test import TestCase

from .models import Compute


class ComputesTestCase(TestCase):
    def setUp(self):
        self.client.login(username="admin", password="admin")
        Compute(
            name="local",
            hostname="localhost",
            login="",
            password="",
            details="local",
            type=4,
        ).save()

    def test_index(self):
        response = self.client.get(reverse("computes"))
        self.assertEqual(response.status_code, 200)

    def test_create_update_delete(self):
        response = self.client.get(reverse("add_socket_host"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("add_socket_host"),
            {
                "name": "l1",
                "details": "Created",
                "hostname": "localhost",
                "type": 4,
            },
        )
        self.assertRedirects(response, reverse("computes"))

        compute = Compute.objects.get(pk=2)
        self.assertEqual(compute.name, "l1")
        self.assertEqual(compute.details, "Created")

        response = self.client.get(reverse("compute_update", args=[2]))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("compute_update", args=[2]),
            {
                "name": "l2",
                "details": "Updated",
                "hostname": "localhost",
                "type": 4,
            },
        )
        self.assertRedirects(response, reverse("computes"))

        compute = Compute.objects.get(pk=2)
        self.assertEqual(compute.name, "l2")
        self.assertEqual(compute.details, "Updated")

        response = self.client.get(reverse("compute_delete", args=[2]))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse("compute_delete", args=[2]))
        self.assertRedirects(response, reverse("computes"))

        with self.assertRaises(ObjectDoesNotExist):
            Compute.objects.get(id=2)

    def test_overview(self):
        response = self.client.get(reverse("overview", args=[1]))
        self.assertEqual(response.status_code, 200)

    def test_graph(self):
        response = self.client.get(reverse("compute_graph", args=[1]))
        self.assertEqual(response.status_code, 200)

    def test_instances(self):
        response = self.client.get(reverse("instances", args=[1]))
        self.assertEqual(response.status_code, 200)

    def test_storages(self):
        response = self.client.get(reverse("storages", args=[1]))
        self.assertEqual(response.status_code, 200)

    def test_storage(self):
        pass

    def test_default_storage_volumes(self):
        response = self.client.get(
            reverse("volumes", kwargs={"compute_id": 1, "pool": "default"})
        )
        self.assertEqual(response.status_code, 200)

    def test_default_storage(self):
        response = self.client.get(
            reverse("storage", kwargs={"compute_id": 1, "pool": "default"})
        )
        self.assertEqual(response.status_code, 200)

    def test_networks(self):
        response = self.client.get(reverse("networks", args=[1]))
        self.assertEqual(response.status_code, 200)

    def test_default_network(self):
        response = self.client.get(
            reverse("network", kwargs={"compute_id": 1, "pool": "default"})
        )
        self.assertEqual(response.status_code, 200)

    def test_interfaces(self):
        response = self.client.get(reverse("interfaces", args=[1]))
        self.assertEqual(response.status_code, 200)

    # TODO: add test for single interface

    def test_nwfilters(self):
        response = self.client.get(reverse("nwfilters", args=[1]))
        self.assertEqual(response.status_code, 200)

    # TODO: add test for single nwfilter

    def test_secrets(self):
        response = self.client.get(reverse("virtsecrets", args=[1]))
        self.assertEqual(response.status_code, 200)

    # def test_create_instance_select_type(self):
    #     response = self.client.get(reverse('create_instance_select_type', args=[1]))
    #     self.assertEqual(response.status_code, 200)

    # TODO: create_instance

    def test_machines(self):
        response = self.client.get(
            reverse("machines", kwargs={"compute_id": 1, "arch": "x86_64"})
        )
        self.assertEqual(response.status_code, 200)

    def test_compute_disk_buses(self):
        response = self.client.get(
            reverse(
                "buses",
                kwargs={
                    "compute_id": 1,
                    "arch": "x86_64",
                    "machine": "pc",
                    "disk": "disk",
                },
            )
        )
        self.assertEqual(response.status_code, 200)

    def test_dom_capabilities(self):
        response = self.client.get(
            reverse(
                "domcaps", kwargs={"compute_id": 1, "arch": "x86_64", "machine": "pc"}
            )
        )
        self.assertEqual(response.status_code, 200)
