import os

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from drf_spectacular.generators import SchemaGenerator
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

    def test_an_api_url_that_names_nothing_is_a_json_404_after_authentication(self):
        # it was the HTML error page
        client = APIClient()
        self.assertEqual(client.get("/api/v1/nothere/").status_code, 401)
        client.force_login(get_user_model().objects.create_user("schema_user", password="pw"))
        for url in ("/api/v1/nothere/", "/api/v1/nothere", "/api/v1/instances/1/x/", "/api/", "/api/v1/", "/api/nope/"):
            with self.subTest(url):
                response = client.get(url, follow=True)
                self.assertEqual((response.status_code, response.json()), (404, {"detail": "Not found."}))
        for method in ("head", "options"):
            with self.subTest(method):
                self.assertEqual(getattr(client, method)("/api/v1/nothere/").status_code, 404)
        self.assertEqual(client.get("/api/schema/").status_code, 200)

    def test_a_volume_s_size_is_gib_to_create_and_bytes_to_read(self):
        # one serializer had both: a size read back and sent again asked 2**30 times as much
        schema = SchemaGenerator().get_schema(request=None, public=True)
        create = schema["paths"]["/api/v1/computes/{compute_pk}/storages/{storage_pk}/volumes/"]["post"]
        self.assertEqual(create["requestBody"]["content"]["application/json"]["schema"]["$ref"],
                         "#/components/schemas/CreateVolume")
        components = schema["components"]["schemas"]
        self.assertEqual(components["CreateVolume"]["properties"]["size"]["description"], "Capacity in GiB")
        self.assertEqual(components["Volume"]["properties"]["size"]["description"], "Capacity in bytes")

    def test_a_refusal_s_body_is_documented_with_its_409(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        poweron = schema["paths"]["/api/v1/computes/{compute_pk}/instances/{id}/poweron/"]["post"]
        self.assertEqual(poweron["responses"]["409"]["content"]["application/json"]["schema"]["$ref"],
                         "#/components/schemas/Error")


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
