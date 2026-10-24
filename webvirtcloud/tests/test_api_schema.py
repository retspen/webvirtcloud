import os

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView

SCHEMA_URLS = ["/api/schema/", "/swagger.json", "/swagger/", "/redoc/"]


class APISchemaTestCase(TestCase):
    def test_schema_is_valid_without_warnings(self):
        call_command("spectacular", "--validate", "--fail-on-warn", "--file", os.devnull)

    def test_non_numeric_compute_id_is_not_routed(self):
        admin = get_user_model().objects.create_superuser("schema_admin", "a@example.com", "pw")
        client = APIClient()
        client.force_login(admin)
        self.assertEqual(client.get("/api/v1/computes/abc/instances/").status_code, 404)
        self.assertEqual(client.get("/api/v1/instances/abc/").status_code, 404)


class SchemaPermissionTestCase(TestCase):
    def test_schema_requires_login(self):
        client = APIClient()
        for url in SCHEMA_URLS:
            self.assertEqual(client.get(url).status_code, 401, url)

    def test_any_user_may_read_the_schema(self):
        user = get_user_model().objects.create_user("schema_reader", password="pw")
        client = APIClient()
        client.force_login(user)
        for url in SCHEMA_URLS:
            self.assertEqual(client.get(url).status_code, 200, url)

    def test_view_without_permission_classes_denies_anonymous(self):
        class Probe(APIView):
            def get(self, request):
                return Response({})

        response = Probe.as_view()(APIRequestFactory().get("/probe/"))
        self.assertEqual(response.status_code, 401)
