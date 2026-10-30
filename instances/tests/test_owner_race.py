"""With one owner per VM, two owners added at the same moment, from the VM
page or a user's page: the second waits for the first and is refused. SQLite's
IMMEDIATE transactions serialize them; PostgreSQL takes the ownership lock."""

import threading
import time
from unittest.mock import patch

from accounts.models import UserInstance
from appsettings.models import AppSettings
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TransactionTestCase
from django.urls import reverse
from instances.models import Instance

UUID = "55555555-5555-5555-5555-555555555555"


class OwnerRaceTests(TransactionTestCase):
    def setUp(self):
        AppSettings.objects.update_or_create(
            key="ALLOW_INSTANCE_MULTIPLE_OWNER",
            defaults={"name": "Multiple owners", "value": "False", "choices": "True,False"},
        )
        users = get_user_model().objects
        self.admin = users.create_superuser("race-admin", "race@example.com", "pw")
        self.bob, self.carol = users.create_user("bob"), users.create_user("carol")
        compute = Compute.objects.create(name="c1", hostname="127.0.0.1", login="", password="", type=4)
        self.vm = Instance.objects.create(compute=compute, name="vm", uuid=UUID)

    def post(self, url, data):
        client = Client()
        client.force_login(self.admin)
        try:
            self.answers.append(client.post(url, data).status_code)
        finally:
            connection.close()

    def test_from_the_vm_page(self):
        add = reverse("instances:add_owner", args=[self.vm.pk])
        self.race(lambda: self.post(add, {"user_id": self.bob.pk}),
                  lambda: self.post(add, {"user_id": self.carol.pk}))

    def test_from_the_vm_page_and_a_user_s_page(self):
        add = reverse("instances:add_owner", args=[self.vm.pk])
        create = reverse("accounts:user_instance_create", args=[self.carol.pk])
        self.race(lambda: self.post(add, {"user_id": self.bob.pk}),
                  lambda: self.post(create, {"user": self.carol.pk, "instance": self.vm.pk}))

    def race(self, first, second):
        """first stops after its check, with its transaction open, while
        second runs; second must then find first's owner. Both answer: the
        VM page redirects, a refused user's page shows the form again."""
        self.answers = []
        checked, go = threading.Event(), threading.Event()
        real = UserInstance.objects.get_or_create

        def slow_get_or_create(**kwargs):
            checked.set()
            go.wait(10)
            return real(**kwargs)

        with patch.object(UserInstance.objects, "get_or_create", slow_get_or_create):
            a = threading.Thread(target=first)
            a.start()
            self.assertTrue(checked.wait(10))
            b = threading.Thread(target=second)
            b.start()
            time.sleep(1)  # second would add its owner now if nothing held it
            go.set()
            a.join(30)
            b.join(30)

        self.assertEqual(len(self.answers), 2)
        self.assertTrue(set(self.answers) <= {200, 302}, self.answers)
        self.assertEqual(list(UserInstance.objects.values_list("user__username", flat=True)), ["bob"])
