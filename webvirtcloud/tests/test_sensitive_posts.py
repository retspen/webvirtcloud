"""The views that take a password or a key mark their POST data sensitive:
an error report (mail_admins) leaves it out."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from computes.models import Compute
from instances.models import Instance


class SensitivePostTestCase(TestCase):
    def test_each_view_that_takes_a_secret_hides_its_post_data(self):
        admin = get_user_model().objects.create_superuser("sens-admin", "s@example.com", "pw")
        compute = Compute.objects.create(name="sens-c", hostname="192.0.2.90", login="root", password="", type=1)
        vm = Instance.objects.create(compute=compute, name="sens-vm", uuid="aaaaaaaa-0000-0000-0000-000000000091")
        self.client.force_login(admin)
        self.client.raise_request_exception = False
        urls = [reverse("admin:user_create"), reverse("admin:user_update", args=[admin.pk]),
                reverse("admin:user_update_password", args=[admin.pk]), reverse("accounts:change_password"),
                reverse("add_tcp_host"), reverse("compute_update", args=[compute.pk]),
                reverse("virtsecrets", args=[compute.pk]),
                reverse("instances:rootpasswd", args=[vm.pk]), reverse("instances:update_console", args=[vm.pk])]
        with patch("instances.models.wvmInstance"), patch("virtsecrets.views.wvmSecrets"):
            for url in urls:
                with self.subTest(url):
                    response = self.client.post(url, {"password": "S3cret"})
                    self.assertEqual(response.wsgi_request.sensitive_post_parameters, "__ALL__")
