from unittest.mock import patch
from accounts.models import UserInstance
from computes.api.serializers import ComputeSerializer
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from instances.models import Flavor, Instance
from operations import claims
from rest_framework.test import APIClient

User = get_user_model()


class APISecurityTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            username="admin_api_test",
            email="admin_api@example.com",
            password="adminpassword",
        )
        self.regular_user = User.objects.create_user(
            username="regular_api_user",
            email="user@example.com",
            password="userpassword",
        )
        self.staff_user = User.objects.create_user(
            username="staff_api_user",
            email="staff@example.com",
            password="staffpassword",
            is_staff=True,
            is_superuser=False,
        )
        self.compute = Compute.objects.create(
            name="api-test-compute",
            hostname="127.0.0.1",
            login="libvirt_user",
            password="hv-secret-pw",
            type=1,
        )
        self.empty_compute = Compute.objects.create(
            name="empty-test-compute",
            hostname="127.0.0.1",
            login="libvirt_user",
            password="hv-secret-pw",
            type=1,
        )
        self.flavor = Flavor.objects.create(
            label="test-flavor",
            vcpu=2,
            memory=2048,
            disk=20,
        )
        self.instance1 = Instance.objects.create(
            compute=self.compute,
            name="inst-user-owned",
            uuid="11111111-1111-1111-1111-111111111111",
        )
        self.instance2 = Instance.objects.create(
            compute=self.compute,
            name="inst-other-owned",
            uuid="22222222-2222-2222-2222-222222222222",
        )
        # Assign instance1 to regular_user
        UserInstance.objects.create(user=self.regular_user, instance=self.instance1)

    def test_compute_serializer_password_is_write_only(self):
        serializer = ComputeSerializer(instance=self.compute)
        self.assertNotIn("password", serializer.data)
        self.assertEqual(serializer.data["name"], "api-test-compute")
        self.assertEqual(serializer.data["login"], "libvirt_user")

    def test_compute_viewset_permissions(self):
        # Anonymous - redirected to login by LoginRequiredMiddleware
        res = self.client.get("/api/v1/computes/")
        self.assertIn(res.status_code, [302, 401, 403])

        # Regular user - forbidden by IsSuperUser
        self.client.force_login(self.regular_user)
        res = self.client.get("/api/v1/computes/")
        self.assertEqual(res.status_code, 403)

        # Staff user (not superuser) - forbidden by IsSuperUser
        self.client.force_login(self.staff_user)
        res = self.client.get("/api/v1/computes/")
        self.assertEqual(res.status_code, 403)

        # Admin user - allowed
        self.client.force_login(self.admin)
        res = self.client.get("/api/v1/computes/")
        self.assertEqual(res.status_code, 200)

    @patch("computes.utils.refresh_instance_database")
    def test_compute_instance_list_isolation(self, mock_refresh):
        # Regular user should only see instance1 on compute
        self.client.force_login(self.regular_user)
        res = self.client.get(f"/api/v1/computes/{self.compute.id}/instances/")
        self.assertEqual(res.status_code, 200)
        names = [item["name"] for item in res.data]
        self.assertIn("inst-user-owned", names)
        self.assertNotIn("inst-other-owned", names)
        mock_refresh.assert_called_once_with(self.compute)

        # Regular user accessing compute where they have NO instances:
        # returns empty list without calling refresh_instance_database!
        mock_refresh.reset_mock()
        res_empty = self.client.get(f"/api/v1/computes/{self.empty_compute.id}/instances/")
        self.assertEqual(res_empty.status_code, 200)
        self.assertEqual(res_empty.data, [])
        mock_refresh.assert_not_called()

        # Admin user should see both instances
        self.client.force_login(self.admin)
        res = self.client.get(f"/api/v1/computes/{self.compute.id}/instances/")
        self.assertEqual(res.status_code, 200)
        names = [item["name"] for item in res.data]
        self.assertIn("inst-user-owned", names)
        self.assertIn("inst-other-owned", names)

    def test_flavor_permissions(self):
        # Regular user can read flavors
        self.client.force_login(self.regular_user)
        res = self.client.get("/api/v1/flavor/")
        self.assertEqual(res.status_code, 200)

        # Regular user cannot mutate flavors
        res = self.client.post(
            "/api/v1/flavor/",
            {"label": "malicious", "vcpu": 4, "memory": 4096, "disk": 40},
        )
        self.assertEqual(res.status_code, 403)

        # Staff user (not superuser) cannot mutate flavors
        self.client.force_login(self.staff_user)
        res = self.client.post(
            "/api/v1/flavor/",
            {"label": "staffmutate", "vcpu": 4, "memory": 4096, "disk": 40},
        )
        self.assertEqual(res.status_code, 403)

        res = self.client.delete(f"/api/v1/flavor/{self.flavor.id}/")
        self.assertEqual(res.status_code, 403)

    def test_migrate_viewset_permissions(self):
        self.client.force_login(self.regular_user)
        res = self.client.post("/api/v1/migrate/", {})
        self.assertEqual(res.status_code, 403)

        self.client.force_login(self.staff_user)
        res = self.client.post("/api/v1/migrate/", {})
        self.assertEqual(res.status_code, 403)

    def test_network_viewset_permissions(self):
        self.client.force_login(self.regular_user)
        res = self.client.get(f"/api/v1/computes/{self.compute.id}/networks/")
        self.assertEqual(res.status_code, 403)

        self.client.force_login(self.staff_user)
        res = self.client.get(f"/api/v1/computes/{self.compute.id}/networks/")
        self.assertEqual(res.status_code, 403)

    def test_interface_viewset_permissions(self):
        self.client.force_login(self.regular_user)
        res = self.client.get(f"/api/v1/computes/{self.compute.id}/interfaces/")
        self.assertEqual(res.status_code, 403)

        self.client.force_login(self.staff_user)
        res = self.client.get(f"/api/v1/computes/{self.compute.id}/interfaces/")
        self.assertEqual(res.status_code, 403)

    def test_storage_viewset_permissions(self):
        self.client.force_login(self.regular_user)
        res = self.client.get(f"/api/v1/computes/{self.compute.id}/storages/")
        self.assertEqual(res.status_code, 403)

        self.client.force_login(self.staff_user)
        res = self.client.get(f"/api/v1/computes/{self.compute.id}/storages/")
        self.assertEqual(res.status_code, 403)

    def test_busy_instance_api_does_not_report_success(self):
        self.client.force_login(self.regular_user)
        with patch("instances.views.libvirt_instance_lock", side_effect=claims.Busy("instance:wvc-test")), patch(
            "instances.models.wvmInstance"
        ) as proxy:
            response = self.client.post(
                f"/api/v1/computes/{self.compute.pk}/instances/{self.instance1.pk}/poweron/", {}
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("short operation", response.json()["detail"])
        self.assertIsNone(response.json()["operation"])
        proxy.assert_not_called()
