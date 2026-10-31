import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone as django_timezone
from django.utils import translation

from operations import jobs
from operations.jobs import Outcome
from operations.models import Claim, Operation, WorkerLease
from operations.templatetags.operations import STATE_COLORS, STATE_LABELS, state_color, state_label
from operations.tests import fakes


class StateColorsTestCase(SimpleTestCase):
    def test_every_state_has_its_colour(self):
        # job_panel.test.js checks the same map in job_panel.js
        self.assertEqual(STATE_COLORS, {
            "queued": "secondary", "running": "primary", "cancelling": "info", "succeeded": "success",
            "failed": "danger", "cancelled": "secondary", "uncertain": "warning",
        })
        self.assertEqual(set(STATE_COLORS), {state for state, _label in Operation.STATES})
        self.assertEqual(state_color("failed"), "danger")

    def test_every_state_has_its_label(self):
        self.assertEqual({state: str(label) for state, label in STATE_LABELS.items()},
                         {state: state for state, _label in Operation.STATES})
        self.assertEqual(state_label("uncertain"), "uncertain")


class JobsPageTestCase(TransactionTestCase):
    def setUp(self):
        fakes.reset()
        U = get_user_model()
        self.user = U.objects.create_user("page_user", "p@example.com", "pw")
        self.admin = U.objects.create_superuser("page_admin", "a@example.com", "pw")
        self.op = jobs.submit("test.noop", self.user, {}, "key-00000001")

    def test_a_user_sees_own_jobs_only(self):
        other = get_user_model().objects.create_user("page_other", "o@example.com", "pw")
        self.client.force_login(other)
        self.assertNotContains(self.client.get(reverse("operations:jobs")), "No-op")
        self.assertEqual(self.client.get(reverse("operations:job", args=[self.op.pk])).status_code, 404)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("operations:jobs")), "No-op")

    def test_superusers_filter_by_compute_and_state(self):
        self.client.force_login(self.admin)
        link = reverse("operations:job", args=[self.op.pk])
        self.assertContains(self.client.get(reverse("operations:jobs"), {"compute": "c"}), link)
        self.assertNotContains(self.client.get(reverse("operations:jobs"), {"state": "failed"}), link)

    def test_host_and_user_filters_match_part_of_the_name(self):
        self.client.force_login(self.admin)
        link = reverse("operations:job", args=[self.op.pk])
        for filters in ({"compute": "C"}, {"username": "PAGE_U"}):
            self.assertContains(self.client.get(reverse("operations:jobs"), filters), link)
        self.assertNotContains(self.client.get(reverse("operations:jobs"), {"username": "other"}), link)

    def test_resolve_needs_a_superuser_an_outcome_and_a_note(self):
        jobs.finish(self.op, Outcome(Operation.UNCERTAIN, error="check"))
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("operations:resolve", args=[self.op.pk]),
                                          {"outcome": "failed", "note": "x"}).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(reverse("operations:resolve", args=[self.op.pk]), {"outcome": "failed", "note": ""})
        self.assertTrue(Claim.objects.filter(operation=self.op).exists())
        self.client.post(reverse("operations:resolve", args=[self.op.pk]), {"outcome": "failed", "note": "checked"})
        self.assertFalse(Claim.objects.filter(operation=self.op).exists())

    def test_the_detail_shows_what_recovery_saw_escaped(self):
        Operation.objects.filter(pk=self.op.pk).update(error="<script>x</script>", phase="Waiting for recovery",
                                                       state=Operation.UNCERTAIN)
        self.client.force_login(self.user)
        response = self.client.get(reverse("operations:job", args=[self.op.pk]))
        self.assertNotContains(response, "<script>x</script>")
        self.assertContains(response, "Waiting for recovery")

    def test_the_detail_shows_the_results_warning_escaped(self):
        Operation.objects.filter(pk=self.op.pk).update(result={"warning": "not <b>thawed</b>"},
                                                       state=Operation.SUCCEEDED)
        self.client.force_login(self.user)
        response = self.client.get(reverse("operations:job", args=[self.op.pk]))
        self.assertContains(response, "not &lt;b&gt;thawed&lt;/b&gt;")

    def test_pagination_keeps_the_filters(self):
        for i in range(51):
            Operation.objects.create(kind="test.noop", user=self.user, username="page_user",
                                     submission_key=f"page-{i:08d}", resource="r", resource_label="c/vm")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("operations:jobs"), {"compute": "c"})
        self.assertContains(response, "compute=c")
        self.assertContains(response, "page=2")

    def _pages_seen_by(self, user):
        Operation.objects.filter(pk=self.op.pk).update(resource_label="wvc-test-host/wvc-test-vm")
        self.client.force_login(user)
        return [self.client.get(reverse("operations:jobs")), self.client.get(reverse("operations:job", args=[self.op.pk]))]

    def test_a_plain_owner_sees_only_the_vm_name(self):
        for response in self._pages_seen_by(self.user):
            self.assertContains(response, "wvc-test-vm")
            self.assertNotContains(response, "wvc-test-host")

    def test_users_who_may_see_hosts_see_the_compute_name(self):
        self.user.user_permissions.add(Permission.objects.get(codename="view_instances",
                                                              content_type__app_label="instances"))
        for response in self._pages_seen_by(self.user) + self._pages_seen_by(self.admin):
            self.assertContains(response, "wvc-test-host")
            self.assertContains(response, "wvc-test-vm")

    def test_the_list_wraps_a_resource_after_its_slash_only(self):
        Operation.objects.filter(pk=self.op.pk).update(resource_label="wvc-test-host/wvc-test-<vm>")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("operations:jobs")),
                            '<span class="text-nowrap">wvc-test-host</span>/<wbr>'
                            '<span class="text-nowrap">wvc-test-&lt;vm&gt;</span>')

    @override_settings(TIME_ZONE="Europe/Istanbul")
    def test_dates_show_in_the_app_format_and_time_zone(self):
        at = datetime(2026, 10, 13, 20, 4, 0, 801375, tzinfo=timezone.utc)
        Operation.objects.filter(pk=self.op.pk).update(created_at=at, started_at=at, finished_at=at,
                                                       state=Operation.SUCCEEDED)
        self.client.force_login(self.admin)
        for response in (self.client.get(reverse("operations:jobs")),
                         self.client.get(reverse("operations:job", args=[self.op.pk]))):
            self.assertContains(response, "2026-10-13 23:04:00 +03")
            self.assertNotContains(response, "2026-10-13T20:04")

    def test_the_job_page_shows_how_long_it_waited_and_ran(self):
        at = datetime(2026, 10, 13, 20, 4, 0, tzinfo=timezone.utc)
        Operation.objects.filter(pk=self.op.pk).update(created_at=at, started_at=at + timedelta(seconds=3),
                                                       finished_at=at + timedelta(minutes=4, seconds=3),
                                                       state=Operation.SUCCEEDED)
        self.client.force_login(self.user)
        response = self.client.get(reverse("operations:job", args=[self.op.pk]))
        self.assertContains(response, "queued for 3 seconds")
        self.assertContains(response, "ran for 4\xa0minutes")
        # cancelled while queued: it never started
        Operation.objects.filter(pk=self.op.pk).update(started_at=None, state=Operation.CANCELLED)
        response = self.client.get(reverse("operations:job", args=[self.op.pk]))
        self.assertNotContains(response, "queued for")
        self.assertNotContains(response, "ran for")
        self.assertContains(response, "Finished")

    def test_list_and_detail_refresh_while_a_job_is_active(self):
        self.client.force_login(self.user)
        pages = (reverse("operations:jobs"), reverse("operations:job", args=[self.op.pk]))
        for url in pages:  # the job is queued
            self.assertContains(self.client.get(url), 'id="follow-active-jobs"')
        Operation.objects.filter(pk=self.op.pk).update(state=Operation.SUCCEEDED)
        for url in pages:
            self.assertNotContains(self.client.get(url), 'id="follow-active-jobs"')

    def test_list_and_detail_show_a_state_badge(self):
        Operation.objects.filter(pk=self.op.pk).update(state=Operation.FAILED, error="disk busy")
        self.client.force_login(self.admin)
        for response in (self.client.get(reverse("operations:jobs")),
                         self.client.get(reverse("operations:job", args=[self.op.pk]))):
            self.assertContains(response, '<span class="badge bg-danger">failed</span>')
        detail = self.client.get(reverse("operations:job", args=[self.op.pk]))
        self.assertContains(detail, 'class="alert alert-danger"')

    def test_the_list_shows_the_phase_while_active_and_the_error_after_a_failure(self):
        Operation.objects.filter(pk=self.op.pk).update(state=Operation.RUNNING, phase="Copying", error="")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("operations:jobs")), "Copying")
        Operation.objects.filter(pk=self.op.pk).update(state=Operation.SUCCEEDED)
        self.assertNotContains(self.client.get(reverse("operations:jobs")), "Copying")
        Operation.objects.filter(pk=self.op.pk).update(state=Operation.FAILED, error="x" * 200)
        response = self.client.get(reverse("operations:jobs"))
        self.assertNotContains(response, "Copying")
        self.assertContains(response, "x" * 79 + "\u2026")

    def test_the_filters_offer_states_and_kinds_and_a_reset(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("operations:jobs"), {"state": "queued", "kind": "test.noop"})
        self.assertContains(response, '<option value="queued" selected>queued</option>')
        self.assertContains(response, '<option value="test.noop" selected>No-op</option>')
        self.assertContains(response, f'href="{reverse("operations:jobs")}"')
        self.assertNotContains(response, 'class="pagination')

    def test_the_worker_warning_shows_when_a_visible_job_waits_for_a_stale_worker(self):
        # the panel uses the same rule (job_panel.test.js)
        stale = django_timezone.now() - timedelta(minutes=2)
        WorkerLease.objects.create(name="worker", holder="h:1:a", host="h", heartbeat_at=stale)
        self.client.force_login(self.user)
        for state, warned in ((Operation.QUEUED, True), (Operation.RUNNING, True), (Operation.CANCELLING, True),
                              (Operation.UNCERTAIN, False), (Operation.SUCCEEDED, False)):
            Operation.objects.filter(pk=self.op.pk).update(state=state, worker="" if state == Operation.QUEUED else "h:1:a")
            response = self.client.get(reverse("operations:jobs"))
            (self.assertContains if warned else self.assertNotContains)(response, "Worker unavailable", msg_prefix=state)
        # a job a request runs does not wait for the worker
        for state in (Operation.RUNNING, Operation.CANCELLING):
            Operation.objects.filter(pk=self.op.pk).update(state=state, worker=Operation.REQUEST)
            self.assertNotContains(self.client.get(reverse("operations:jobs")), "Worker unavailable", msg_prefix=state)
        Operation.objects.filter(pk=self.op.pk).update(state=Operation.RUNNING, worker="h:1:a")
        WorkerLease.objects.update(heartbeat_at=django_timezone.now())
        self.assertNotContains(self.client.get(reverse("operations:jobs")), "Worker unavailable")
        # another user's running job is not this user's concern
        other = get_user_model().objects.create_user("page_other2", "o2@example.com", "pw")
        WorkerLease.objects.update(heartbeat_at=stale)
        self.client.force_login(other)
        self.assertNotContains(self.client.get(reverse("operations:jobs")), "Worker unavailable")

    def test_an_uncertain_badge_has_dark_text(self):
        Operation.objects.filter(pk=self.op.pk).update(state=Operation.UNCERTAIN)
        self.client.force_login(self.admin)
        # the app's theme draws white text on bg-warning
        self.assertContains(self.client.get(reverse("operations:jobs")),
                            '<span class="badge bg-warning text-dark">uncertain</span>')

    def test_a_narrow_list_shows_resource_and_user_under_the_job(self):
        Operation.objects.filter(pk=self.op.pk).update(resource_label="wvc-test-host/wvc-test-vm")
        self.client.force_login(self.admin)
        html = self.client.get(reverse("operations:jobs")).content.decode()
        # below md only Job and State are columns
        for header in ("Resource", "User"):
            self.assertIn(f'<th scope="col" class="d-none d-md-table-cell">{header}</th>', html)
        self.assertIn('<span class="d-md-none"> &middot; page_user</span>', html)
        narrow = re.search(r'<div class="d-md-none small">(.*?)</div>', html, re.S).group(1)
        self.assertIn('<span class="text-nowrap">wvc-test-vm</span>', narrow)
        # a plain user's list has no user
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("operations:jobs")), "&middot; page_user")

    def test_the_list_shows_an_active_jobs_progress(self):
        Operation.objects.filter(pk=self.op.pk).update(state=Operation.RUNNING, progress_done=3, progress_total=10)
        self.client.force_login(self.user)
        response = self.client.get(reverse("operations:jobs"))
        self.assertContains(response, "3 / 10")
        self.assertContains(response, 'aria-valuenow="30"')
        Operation.objects.filter(pk=self.op.pk).update(state=Operation.SUCCEEDED)
        self.assertNotContains(self.client.get(reverse("operations:jobs")), 'role="progressbar"')

    def test_states_and_phases_show_translated(self):
        Operation.objects.filter(pk=self.op.pk).update(state=Operation.RUNNING, phase="Merging the snapshot")
        self.client.force_login(self.admin)
        fake = lambda *args: f"T[{args[-1]}]"  # noqa: E731
        with patch.object(translation._trans, "gettext", side_effect=fake), \
                patch.object(translation._trans, "pgettext", side_effect=fake):
            listed = self.client.get(reverse("operations:jobs"))
            detail = self.client.get(reverse("operations:job", args=[self.op.pk]))
        for response in (listed, detail):
            self.assertContains(response, '<span class="badge bg-primary">T[running]</span>')
            self.assertContains(response, "T[Merging the snapshot]")
        self.assertContains(listed, '<option value="failed">T[failed]</option>')

    def test_the_detail_shows_progress_in_bytes_for_kinds_that_count_bytes(self):
        Operation.objects.filter(pk=self.op.pk).update(progress_done=3 * 1024 ** 3, progress_total=6 * 1024 ** 3)
        self.client.force_login(self.admin)
        url = reverse("operations:job", args=[self.op.pk])
        response = self.client.get(url)
        self.assertContains(response, 'aria-valuenow="50"')
        self.assertContains(response, str(3 * 1024 ** 3))
        with patch.object(fakes.NoopKind, "progress_bytes", True):
            self.assertContains(self.client.get(url), "3.0\xa0GB / 6.0\xa0GB")
