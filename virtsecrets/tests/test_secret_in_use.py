"""A secret a VM or a pool needs is not deleted: without it that VM or pool
no longer starts. A VM names its secret in a disk, a host device or its vTPM,
a pool in its source, by UUID or by usage within the usage type; as they run
and as saved. libvirt's test driver has no secrets, so the connection is a
mock."""

from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from vrtManager.util import OperationError
from vrtManager.tests.fakes import CEPH


class SecretInUsePageTests(TestCase):
    def setUp(self):
        compute = Compute.objects.create(name="secret-use", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("secret-use", "su@example.com", "pw"))
        self.url = reverse("virtsecrets", args=[compute.id])

    def test_the_page_says_who_needs_it(self):
        with patch("virtsecrets.views.wvmSecrets") as conn:
            conn.return_value.delete_secret.side_effect = OperationError(f"Secret {CEPH} is used by VMs db-2")
            response = self.client.post(self.url, {"delete": "", "uuid": CEPH})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], [f"Secret {CEPH} is used by VMs db-2"])

    def test_a_post_to_a_host_not_reached_is_redirected(self):
        with patch("virtsecrets.views.wvmSecrets", side_effect=libvirt.libvirtError("unable to connect")):
            response = self.client.post(self.url, {"delete": "", "uuid": CEPH})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)

    def test_the_list_is_not_shown_without_its_users(self):
        # it would offer to delete the secrets in use
        with patch("virtsecrets.views.wvmSecrets") as conn:
            conn.return_value.get_secrets_info.return_value = [{"uuid": CEPH, "usage_type": "ceph", "usage": "client.libvirt",
                                                                "ephemeral": False, "private": False}]
            conn.return_value.get_users.side_effect = libvirt.libvirtError("connection reset")
            response = self.client.get(self.url)
        self.assertEqual(response.context["secrets_all"], [])
