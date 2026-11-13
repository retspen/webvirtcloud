"""The Computes page reads its hosts side by side: a host that does not
answer holds back only itself, and only up to the page's wait."""

import threading
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from computes.models import Compute


class ListHostsTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("lh-admin", "lh@example.com", "pw"))
        for number, name in enumerate(("fast", "slow-1", "slow-2")):
            Compute.objects.create(name=name, hostname="192.0.2.1", login="wvc", password="", type=1,
                                   host_uuid=f"{number}" * 8 + "-0000-0000-0000-000000000000")
        self.release = threading.Event()
        self.addCleanup(self.release.set)

    def read(self, compute):
        if compute.name.startswith("slow"):
            self.release.wait(5)
        return True, None, None, ""

    def test_hosts_that_do_not_answer_are_waited_for_together_and_shown_so(self):
        with patch("computes.views._read_host", side_effect=self.read), patch("computes.views.LIST_WAIT", 0.5):
            started = time.monotonic()
            response = self.client.get(reverse("computes"))
            took = time.monotonic() - started
        self.assertLess(took, 2)  # one wait for both, not one each
        shown = {compute.name: (compute.status, compute.connection_error) for compute in response.context["computes"]}
        self.assertEqual(shown["fast"], (True, None))
        self.assertEqual(shown["slow-1"], (False, "The host did not answer within 0.5 seconds"))
        self.assertEqual(response.context["totals"]["connected"], 1)

    def test_a_host_still_being_read_is_not_read_again(self):
        with patch("computes.views._read_host", side_effect=self.read) as read, patch("computes.views.LIST_WAIT", 0.2):
            self.client.get(reverse("computes"))
            self.client.get(reverse("computes"))
            self.assertEqual(sorted(call.args[0].name for call in read.call_args_list),
                             ["fast", "fast", "slow-1", "slow-2"])

    def test_many_hosts_that_do_not_answer_leave_the_others_read(self):
        # each host has its own thread: nine stuck hosts, read first, take no place of the one that answers
        for number in range(3, 10):
            Compute.objects.create(name=f"slow-{number}", hostname="192.0.2.1", login="wvc", password="", type=1,
                                   host_uuid=f"{number}" * 8 + "-0000-0000-0000-000000000000")
        Compute.objects.filter(name="fast").update(name="z-fast")  # the page lists by name: the last one
        with patch("computes.views._read_host", side_effect=self.read), patch("computes.views.LIST_WAIT", 0.5):
            response = self.client.get(reverse("computes"))
        shown = {compute.name: compute.status for compute in response.context["computes"]}
        self.assertIs(shown["z-fast"], True)
        self.assertEqual(sum(status is False for status in shown.values()), 9)

    def test_a_compute_given_another_host_is_read_anew(self):
        # a read of its old host still running: its answer is not the new host's
        old = Compute.objects.get(name="slow-1")
        with patch("computes.views._read_host", side_effect=self.read) as read, patch("computes.views.LIST_WAIT", 0.2):
            self.client.get(reverse("computes"))
            Compute.objects.filter(pk=old.pk).update(hostname="192.0.2.99")
            self.client.get(reverse("computes"))
        hosts = [call.args[0].hostname for call in read.call_args_list if call.args[0].pk == old.pk]
        self.assertEqual(hosts, ["192.0.2.1", "192.0.2.99"])

    def test_a_host_uuid_is_read_with_the_host_and_kept(self):
        # one added before host UUIDs were kept: read within the list's wait, saved after it
        Compute.objects.filter(name="fast").update(host_uuid="")
        uuid = "abcdabcd-0000-0000-0000-000000000000"
        with patch("computes.views._read_host", return_value=(True, None, None, uuid)):
            self.client.get(reverse("computes"))
        self.assertEqual(Compute.objects.get(name="fast").host_uuid, uuid)
