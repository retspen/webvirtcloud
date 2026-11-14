"""A request the permission check refuses takes no claim: it cannot hold up
other requests on the VM or its compute."""

from contextlib import contextmanager
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance


class ClaimAfterPermissionTestCase(TestCase):
    def setUp(self):
        compute = Compute.objects.create(name="claim-c", hostname="192.0.2.80", login="root", password="", type=1)
        self.vm = Instance.objects.create(compute=compute, name="claim-vm", uuid="aaaaaaaa-0000-0000-0000-000000000081")
        self.claims = []

        @contextmanager
        def record(*args, **kwargs):
            self.claims.append(args)
            yield

        for name in ("libvirt_instance_lock", "libvirt_compute_lock"):
            patcher = patch(f"instances.views.{name}", record)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_read_only_viewer_takes_no_claim(self):
        viewer = get_user_model().objects.create_user("claim-viewer", password="x")
        viewer.user_permissions.add(Permission.objects.get(codename="view_instances"))
        self.client.force_login(viewer)
        for view in ("poweron", "destroy"):
            with self.subTest(view):
                self.assertEqual(self.client.post(reverse(f"instances:{view}", args=[self.vm.pk])).status_code, 403)
        self.assertEqual(self.claims, [])

    def test_an_owner_who_may_not_delete_takes_no_compute_claim(self):
        owner = get_user_model().objects.create_user("claim-owner", password="x")
        UserInstance.objects.create(instance=self.vm, user=owner, is_delete=False)
        self.client.force_login(owner)
        self.assertEqual(self.client.post(reverse("instances:destroy", args=[self.vm.pk])).status_code, 403)
        self.assertEqual(self.claims, [])
