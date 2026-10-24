"""Failures reach the user: safe redirects, failure statuses, no silent success."""

import inspect
from unittest.mock import patch

from accounts.models import UserInstance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import URLPattern, get_resolver, reverse
from logs.models import Logs
from vrtManager.util import OperationError

from instances.models import Instance

EXTERNAL = "https://evil.example/instances/1/"


def back_views():
    """URL names of the instance views that return with _back(), also through _snapshot_job()."""
    names = []
    for pattern in get_resolver().url_patterns:
        if getattr(pattern, "namespace", None) != "instances":
            continue
        for sub in pattern.url_patterns:
            if isinstance(sub, URLPattern) and any(
                call in inspect.getsource(inspect.unwrap(sub.callback))
                for call in ("_back(request, pk", "_snapshot_job(request, pk")
            ):
                names.append(sub.name)
    return names


class ErrorHandlingTestCase(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser("err_admin", "e@example.com", "pw")
        self.client.force_login(admin)
        self.compute = Compute.objects.create(name="err-compute", hostname="127.0.0.1", login="", password="", type=4)
        self.instance = Instance.objects.create(
            compute=self.compute, name="err-vm", uuid="11111111-2222-3333-4444-555555555555"
        )
        self.page = f"/instances/{self.instance.id}/"

    def url(self, name):
        args = [self.instance.id, "sda"] if name == "detach_cdrom" else [self.instance.id]
        return reverse(f"instances:{name}", args=args)

    # Required fields for the views that 404 without them
    DATA = {
        "add_owner": lambda self: {"user_id": get_user_model().objects.get(username="err_admin").id},
        "del_owner": lambda self: {"userinstance": UserInstance.objects.get_or_create(
            instance=self.instance, user=get_user_model().objects.get(username="err_admin"))[0].id},
        "add_network": lambda self: {"add-net-network": "net:default"},
        "set_qos": lambda self: {"qos_direction": "inbound", "net-mac-0": "52:54:00:00:00:01"},
    }

    def test_redirects_without_or_with_a_foreign_referer_go_to_the_vm_page(self):
        names = back_views()
        self.assertGreaterEqual(len(names), 29)
        for name in names:
            for referer in (None, EXTERNAL):
                with self.subTest(view=name, referer=referer), patch("instances.models.wvmInstance"), \
                        patch("instances.jobs.wvmInstance"):
                    headers = {"HTTP_REFERER": referer} if referer else {}
                    data = self.DATA[name](self) if name in self.DATA else {}
                    response = self.client.post(self.url(name), data, **headers)
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response.url.startswith(self.page + "#"), response.url)

    def test_owner_views_reject_missing_or_foreign_ids(self):
        other = Instance.objects.create(compute=self.compute, name="other", uuid="11111111-2222-3333-4444-777777777777")
        foreign = UserInstance.objects.create(instance=other, user=get_user_model().objects.get(username="err_admin"))
        self.assertEqual(self.client.post(self.url("add_owner"), {}).status_code, 404)
        self.assertEqual(self.client.post(self.url("del_owner"), {}).status_code, 404)
        self.assertEqual(self.client.post(self.url("del_owner"), {"userinstance": foreign.id}).status_code, 404)
        self.assertTrue(UserInstance.objects.filter(pk=foreign.id).exists())

    def test_same_site_referer_is_kept(self):
        with patch("instances.models.wvmInstance"):
            response = self.client.post(self.url("set_autostart"), {}, HTTP_REFERER="http://testserver/instances/?x=1")
        self.assertEqual(response.url, "http://testserver/instances/?x=1#boot_opt")

    def migrate(self, target_id, up=True):
        with patch("instances.models.wvmInstance"), patch.object(Compute, "status", up):
            return self.client.post(self.url("migrate"), {"compute_id": target_id, "submission_key": "key-migrate01"})

    def test_migrate_to_a_down_host_is_reported_and_not_logged_as_done(self):
        target = Compute.objects.create(name="down", hostname="10.0.0.9", login="", password="", type=4)
        response = self.migrate(str(target.id), up=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("not reachable", " ".join(str(m) for m in get_messages(response.wsgi_request)))
        self.assertFalse(Logs.objects.filter(message__contains="migrated").exists())

    def test_migrate_to_the_same_host_is_reported(self):
        response = self.migrate(str(self.compute.id))
        self.assertIn("already on", " ".join(str(m) for m in get_messages(response.wsgi_request)))

    def test_migrate_to_an_invalid_compute_is_404(self):
        self.assertEqual(self.migrate("").status_code, 404)
        self.assertEqual(self.migrate("999").status_code, 404)


class ApiErrorTestCase(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser("api_admin", "a@example.com", "pw")
        self.client.force_login(admin)
        self.compute = Compute.objects.create(name="api-compute", hostname="127.0.0.1", login="", password="", type=4)
        self.instance = Instance.objects.create(
            compute=self.compute, name="api-vm", uuid="11111111-2222-3333-4444-666666666666"
        )

    def test_libvirt_error_is_json_with_a_failure_status(self):
        url = reverse("compute-instance-poweron", kwargs={"compute_pk": self.compute.id, "pk": self.instance.id})
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.start.side_effect = OperationError("cannot start")
            response = self.client.post(url, {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "cannot start"})

    def test_migrate_to_a_down_host_is_not_started(self):
        target = Compute.objects.create(name="api-down", hostname="10.0.0.9", login="", password="", type=4)
        with patch("instances.models.wvmInstance"), patch.object(Compute, "status", False):
            response = self.client.post(
                reverse("instance-migrate-list"), {"instance": self.instance.id, "target_compute": target.id,
                                                "submission_key": "key-migrate02"}
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not reachable", response.json()["detail"])

    def volume(self, method, active=True, data=None):
        kwargs = {"compute_pk": self.compute.id, "storage_pk": "default"}
        with patch("storages.api.viewsets.wvmStorage") as storage:
            storage.return_value.is_active.return_value = active
            if method == "post":
                return self.client.post(reverse("compute-storage-volumes-list", kwargs=kwargs), data or {})
            return self.client.delete(reverse("compute-storage-volumes-detail", kwargs={**kwargs, "pk": "disk.qcow2"}))

    def test_volume_calls_on_an_inactive_pool_fail(self):
        data = {"name": "v", "size": 1, "type": "qcow2", "meta_prealloc": False}
        self.assertEqual(self.volume("post", active=False, data=data).status_code, 409)
        self.assertEqual(self.volume("delete", active=False).status_code, 409)

    def test_invalid_volume_data_is_400_with_the_errors(self):
        response = self.volume("post", data={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json())
