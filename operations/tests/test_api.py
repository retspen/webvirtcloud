from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance
from operations import claims, jobs
from operations.models import Claim, Operation
from operations.tests import fakes
from operations.utils import say


class OperationsApiTestCase(TransactionTestCase):
    def setUp(self):
        fakes.reset()
        U = get_user_model()
        self.owner = U.objects.create_user("api_owner", "o@example.com", "pw")
        self.other = U.objects.create_user("api_other", "x@example.com", "pw")
        compute = Compute.objects.create(name="api-c", hostname="192.0.2.20", login="root", password="", type=1)
        self.vm = Instance.objects.create(compute=compute, name="api-vm", uuid="u1")
        self.vm2 = Instance.objects.create(compute=compute, name="api-vm2", uuid="u2")
        UserInstance.objects.create(user=self.other, instance=self.vm)
        UserInstance.objects.create(user=self.owner, instance=self.vm2)
        self.op = jobs.submit("test.noop", self.owner, {"uuid": "u1"}, "key-00000001")

    def test_the_phase_comes_in_the_users_language_and_says_when_it_is_past_its_limit(self):
        Operation.objects.filter(pk=self.op.pk).update(state=Operation.RUNNING, phase="Merging the snapshot")
        self.client.force_login(self.owner)
        url = f"/api/v1/operations/{self.op.pk}/"
        self.assertEqual(self.client.get(url, HTTP_ACCEPT_LANGUAGE="tr").json()["phase"], "Anlık görüntü birleştiriliyor")
        Operation.objects.filter(pk=self.op.pk).update(time_limit=60, started_at=timezone.now() - timedelta(seconds=61))
        self.assertEqual(self.client.get(url).json()["phase"], "Merging the snapshot (over its time limit)")

    def test_the_error_and_warning_come_in_the_users_language_with_their_values(self):
        # ours with its values; libvirt's text as it is
        Operation.objects.filter(pk=self.op.pk).update(
            state=Operation.FAILED,
            error=say("The pool has no volume named %(name)s", name="disk.qcow2") + say("unable to open: busy"),
            result={"warning": say("The copy was not made")})
        self.client.force_login(self.owner)
        job = self.client.get(f"/api/v1/operations/{self.op.pk}/", HTTP_ACCEPT_LANGUAGE="tr").json()
        self.assertEqual(job["error"], "Havuzda disk.qcow2 adında birim yok. unable to open: busy")
        self.assertEqual(job["result"]["warning"], "Kopya oluşturulmadı")

    def test_users_list_only_their_own_jobs(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get("/api/v1/operations/").json()["count"], 0)
        self.assertEqual(self.client.get(f"/api/v1/operations/{self.op.pk}/").status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/api/v1/operations/").json()["count"], 1)

    def test_the_resource_view_shows_others_jobs_as_summaries(self):
        self.client.force_login(self.other)
        data = self.client.get("/api/v1/operations/resource/", {"key": "instance:u1"}).json()
        self.assertEqual(data["jobs"], [])
        [summary] = data["others"]
        self.assertEqual(summary["kind"], "test.noop")
        for private in ("id", "user", "username", "params"):
            self.assertNotIn(private, summary)

    def test_a_resource_the_user_cannot_see_is_refused(self):
        stranger = get_user_model().objects.create_user("api_s", "s@example.com", "pw")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get("/api/v1/operations/resource/", {"key": "instance:u1"}).status_code, 404)

    def test_a_short_operation_is_flagged(self):
        claims.admit({"instance:u2": Claim.EXCLUSIVE}, holder="another-request")
        self.client.force_login(self.owner)
        self.assertTrue(self.client.get("/api/v1/operations/resource/", {"key": "instance:u2"}).json()["short_operation"])

    def test_the_resource_view_marks_a_job_a_request_runs(self):
        request_job = jobs.submit("test.request", self.owner, {"uuid": "u2"}, "key-00000002")
        self.client.force_login(self.owner)
        [job] = self.client.get("/api/v1/operations/resource/", {"key": "instance:u2"}).json()["jobs"]
        self.assertEqual((job["id"], job["in_request"]), (str(request_job.pk), True))
        # queued: it waits for the worker
        self.assertFalse(self.client.get(f"/api/v1/operations/{self.op.pk}/").json()["in_request"])

    def test_cancel_through_the_api(self):
        self.client.force_login(self.owner)
        response = self.client.post(f"/api/v1/operations/{self.op.pk}/cancel/")
        self.assertEqual((response.status_code, response.json()["state"]), (200, "cancelled"))

    def test_another_users_job_cannot_be_cancelled(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(f"/api/v1/operations/{self.op.pk}/cancel/").status_code, 404)
        self.assertEqual(self.client.post(reverse("operations:cancel", args=[self.op.pk])).status_code, 404)
        self.op.refresh_from_db()
        self.assertEqual(self.op.state, Operation.QUEUED)

    def test_a_job_that_cannot_stop_answers_400(self):
        Operation.objects.filter(pk=self.op.pk).update(state=Operation.RUNNING)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(f"/api/v1/operations/{self.op.pk}/cancel/").status_code, 400)

    def _labels_seen_by(self, user, label="wvc-test-host/wvc-test-vm"):
        op = jobs.submit("test.noop", self.owner, {"uuid": "u2"}, "key-00000002")
        Operation.objects.filter(pk=op.pk).update(resource_label=label)
        self.client.force_login(user)
        listed = [row["resource_label"] for row in self.client.get("/api/v1/operations/").json()["results"]
                  if row["id"] == str(op.pk)]
        detail = self.client.get(f"/api/v1/operations/{op.pk}/").json()["resource_label"]
        [job] = self.client.get("/api/v1/operations/resource/", {"key": "instance:u2"}).json()["jobs"]
        cancelled = self.client.post(f"/api/v1/operations/{op.pk}/cancel/").json()["resource_label"]
        return listed + [detail, job["resource_label"], cancelled]

    def test_a_plain_owner_sees_only_the_vm_name(self):
        self.assertEqual(self._labels_seen_by(self.owner), ["wvc-test-vm"] * 4)

    def test_a_compute_name_with_a_slash_stays_hidden(self):
        # libvirt refuses "/" in VM names; compute names may contain it
        self.assertEqual(self._labels_seen_by(self.owner, "wvc-test-region/wvc-test-host/wvc-test-vm"),
                         ["wvc-test-vm"] * 4)

    def test_users_who_may_see_hosts_see_the_compute_name(self):
        self.owner.user_permissions.add(Permission.objects.get(codename="view_instances",
                                                               content_type__app_label="instances"))
        self.assertEqual(self._labels_seen_by(self.owner), ["wvc-test-host/wvc-test-vm"] * 4)

    def test_superusers_see_the_compute_name(self):
        admin = get_user_model().objects.create_superuser("api_admin", "a@example.com", "pw")
        self.assertEqual(self._labels_seen_by(admin), ["wvc-test-host/wvc-test-vm"] * 4)
