"""
A migration may move a VM between a request reading it and taking its
compute's claim: the request then holds the old compute's claim, not the
new one's. It must not run on the new host but answer "moved, try again",
and the retry claims the right compute.
"""
from contextlib import contextmanager
from unittest.mock import PropertyMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from computes.models import Compute
from instances.jobs import DeleteInstance
from instances.models import Instance
from operations.models import Operation
from vrtManager.util import OperationError


class MovedWhileWaitingTestCase(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("moved_admin", "m@example.com", "x")
        self.source = Compute.objects.create(name="src", hostname="192.0.2.1", login="root", password="", type=1)
        self.target = Compute.objects.create(name="dst", hostname="192.0.2.2", login="root", password="", type=1)
        self.vm = Instance.objects.create(
            compute=self.source, name="moved-vm", uuid="eeeeeeee-ffff-0000-1111-222222222222"
        )
        self.client.force_login(self.admin)

    def poweroff(self, lock):
        with patch("instances.views.libvirt_instance_lock", lock), patch(
            "instances.models.wvmInstance"
        ) as wvm, patch.object(Compute, "status", new_callable=PropertyMock, return_value=True):
            response = self.client.post(reverse("instances:poweroff", args=[self.vm.id]))
        return response, wvm.return_value.shutdown.called

    def test_a_vm_moved_while_the_request_waited_is_not_touched(self):
        @contextmanager
        def lock_after_a_migration(instance):
            # the migration that held the lock moved the VM before releasing it
            Instance.objects.filter(pk=instance.pk).update(compute=self.target)
            yield

        response, touched = self.poweroff(lock_after_a_migration)
        self.assertFalse(touched)
        self.assertEqual(response.status_code, 302)
        messages = [str(m) for m in response.wsgi_request._messages]
        self.assertIn("The VM was moved meanwhile; try again.", messages)

    def test_a_vm_that_stayed_is_changed(self):
        @contextmanager
        def plain_lock(instance):
            yield

        response, touched = self.poweroff(plain_lock)
        self.assertTrue(touched)

    def test_destroy_of_a_vm_moved_while_it_waited_is_not_run(self):
        # the delete job holds the whole compute; a migration moved the VM before it ran
        with patch("instances.models.wvmInstance"):
            self.client.post(reverse("instances:destroy", args=[self.vm.id]),
                             {"delete_disk": "on", "submission_key": "key-moved001"})
        op = Operation.objects.get(kind="instance.delete")
        Instance.objects.filter(pk=self.vm.pk).update(compute=self.target)
        with self.assertRaisesMessage(OperationError, "The VM moved to another compute"):
            DeleteInstance().precheck(op, None)
