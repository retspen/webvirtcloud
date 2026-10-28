"""Live check that asking a host whether it can change interfaces defines
nothing, and that the interfaces page follows the answer. Runs only with
TEST_LIBVIRT_HOST set; TEST_LIBVIRT_SSH_HOST/_LOGIN add an ssh compute."""

import os
import unittest

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from vrtManager.connection import wvmConnect


@unittest.skipUnless(os.environ.get("TEST_LIBVIRT_HOST"), "Set TEST_LIBVIRT_HOST to run the live libvirt tests")
class LiveInterfacesTestCase(TestCase):
    def hosts(self):
        yield "tcp", (
            os.environ["TEST_LIBVIRT_HOST"],
            os.environ.get("TEST_LIBVIRT_LOGIN", ""),
            os.environ.get("TEST_LIBVIRT_PASSWORD", ""),
            int(os.environ.get("TEST_LIBVIRT_TYPE", 1)),
        )
        if os.environ.get("TEST_LIBVIRT_SSH_HOST"):
            yield "ssh", (os.environ["TEST_LIBVIRT_SSH_HOST"], os.environ.get("TEST_LIBVIRT_SSH_LOGIN", "root"), "", 2)

    def test_the_question_defines_nothing_and_the_page_follows_the_answer(self):
        self.client.force_login(get_user_model().objects.create_superuser("live-iface", "li@example.com", "x"))
        for name, args in self.hosts():
            with self.subTest(name):
                conn = wvmConnect(*args)
                before = sorted(i.XMLDesc(0) for i in conn.wvm.listAllInterfaces(0))
                changeable = conn.can_change_interfaces()
                self.assertIsInstance(changeable, bool)
                self.assertEqual(sorted(i.XMLDesc(0) for i in conn.wvm.listAllInterfaces(0)), before)
                hostname, login, password, conn_type = args
                compute = Compute.objects.create(
                    name=f"live-{name}", hostname=hostname, login=login, password=password, type=conn_type
                )
                page = self.client.get(reverse("interfaces", args=[compute.id])).content.decode()
                self.assertEqual("#AddInterface" in page, changeable)
                self.assertEqual("only reads network interfaces" in page, not changeable)
