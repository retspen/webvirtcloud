"""A VM list asks all hosts at once and waits LIST_HOST_WAIT at most: a host
that does not answer (a stuck daemon) is shown not answering, and the other
hosts' VMs are listed."""

import threading
import time
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

from computes.models import Compute
from django.test import TestCase

from instances import utils


class HungHostTests(TestCase):
    def test_a_host_that_does_not_answer_is_left_out_in_time(self):
        hung, ok = (Compute.objects.create(name=name, hostname=f"192.0.2.{n}", login="", password="", type=1)
                    for n, name in ((1, "hung"), (2, "ok")))
        release = threading.Event()
        self.addCleanup(release.set)

        def states(proxy_of):
            def get_domain_states():
                if proxy_of == "hung":
                    release.wait(5)
                return {"u-1": ["vm", 1]}
            return SimpleNamespace(get_domain_states=get_domain_states)

        # each copy of a compute (one per thread) gets the proxy of its host
        with patch.object(Compute, "status", new_callable=PropertyMock, return_value=True), \
                patch.object(Compute, "proxy", property(lambda compute: states(compute.name))), \
                patch.object(utils, "LIST_HOST_WAIT", 0.5):
            start = time.monotonic()
            result = utils.host_domain_states([hung, ok])
            waited = time.monotonic() - start
        self.assertLess(waited, 2)
        self.assertEqual(result, {hung.pk: None, ok.pk: {"u-1": ["vm", 1]}})
        self.assertIs(hung.status, False)
        self.assertIn("did not answer within", str(hung.connection_error))

    def test_a_host_whose_read_fails_is_marked(self):
        # connected, but its answer an error: the page says so and does not ask it again
        from libvirt import libvirtError

        host = Compute.objects.create(name="failing", hostname="192.0.2.3", login="", password="", type=1)

        def fail():
            raise libvirtError("internal error: no domains for you")

        with patch.object(Compute, "status", new_callable=PropertyMock, return_value=True), \
                patch.object(Compute, "proxy", property(lambda compute: SimpleNamespace(get_domain_states=fail))):
            self.assertEqual(utils.host_domain_states([host]), {host.pk: None})
        self.assertIs(host.status, False)
        self.assertIn("no domains for you", str(host.connection_error))
