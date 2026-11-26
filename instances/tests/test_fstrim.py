"""Free unused space: the guest agent trims each mounted file system (instance.fstrim); a disk passes it to its
image only with the discard mode unmap, which the Disks tab and the job say when no disk has it."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TransactionTestCase
from django.urls import reverse

from computes.models import Compute
from instances.jobs import TrimVM
from instances.models import Instance
from operations.jobs import Context
from operations.models import Operation, acquire
from operations.utils import words
from vrtManager import instance as vrt_instance
from vrtManager.util import OperationError


def disk(discard):
    return {"dev": "vda", "discard": discard}


class FstrimTestCase(TransactionTestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("ft-admin", "ft@example.com", "pw")
        self.client.force_login(self.admin)
        compute = Compute.objects.create(name="ft-host", hostname="192.0.2.81", login="", password="", type=4)
        self.vm = Instance.objects.create(compute=compute, name="ft-vm", uuid="81818181-0000-4000-8000-000000000001")
        self.proxy = MagicMock(**{"get_status.return_value": 1, "is_agent_ready.return_value": True,
                                  "get_disk_devices.return_value": [disk("unmap")],
                                  "fstrim.return_value": [{"path": "/", "trimmed": 1 << 30, "error": None}]})
        patch.object(Instance, "proxy", property(lambda vm: self.proxy)).start()
        self.addCleanup(patch.stopall)

    def queue_and_run(self):
        response = self.client.post(reverse("instances:fstrim", args=[self.vm.pk]), {"submission_key": "key-fstrim01"})
        self.assertRedirects(response, reverse("instances:instance", args=[self.vm.pk]) + "#disks",
                             fetch_redirect_response=False)
        op = Operation.objects.get(kind="instance.fstrim")
        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        ctx = Context(op, SimpleNamespace(identity="wvc-test:1:a"))
        TrimVM().precheck(op, ctx)
        return TrimVM().run(op, ctx)

    def test_the_job_returns_what_each_file_system_trimmed(self):
        self.assertEqual(self.queue_and_run(), {"trimmed": [{"path": "/", "trimmed": 1 << 30, "error": None}]})

    def test_without_discard_unmap_the_job_warns_that_the_images_keep_their_size(self):
        self.proxy.get_disk_devices.return_value = [disk("default")]
        result = self.queue_and_run()
        self.assertIn("image files keep their size", words(result["warning"]))

    def test_the_job_fails_when_the_guest_trims_no_file_system(self):
        self.proxy.fstrim.return_value = [{"path": "/", "trimmed": None, "error": "not supported"}]
        with self.assertRaisesMessage(OperationError, "No file system was trimmed: /: not supported"):
            self.queue_and_run()
        self.assertTrue(Operation.objects.get().effects_started)  # recovery knows the guest was asked

    def test_only_a_superuser_still_active_trims(self):
        owner = get_user_model().objects.create_user("ft-owner", "o@example.com", "pw")
        self.client.force_login(owner)
        self.assertEqual(self.client.post(reverse("instances:fstrim", args=[self.vm.pk]),
                                          {"submission_key": "key-fstrim02"}).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(reverse("instances:fstrim", args=[self.vm.pk]), {"submission_key": "key-fstrim03"})
        op = Operation.objects.get()
        self.admin.is_superuser = False
        self.admin.save()
        op.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            TrimVM().precheck(op, None)

    def test_a_vm_not_running_or_without_an_agent_is_refused(self):
        self.proxy.get_status.return_value = 5
        with self.assertRaisesMessage(OperationError, "not running"):
            self.queue_and_run()
        self.proxy.fstrim.assert_not_called()

    def test_the_job_page_lists_each_file_system(self):
        op = Operation.objects.create(kind="instance.fstrim", user=self.admin, username="ft-admin", resource="r",
                                      resource_label="ft-host/ft-vm", state=Operation.SUCCEEDED, result={"trimmed": [
                                          {"path": "/", "trimmed": 1 << 30, "error": None},
                                          {"path": "/boot", "trimmed": None, "error": "not supported"}]})
        page = self.client.get(reverse("operations:job", args=[op.pk])).content.decode()
        self.assertInHTML("<li class=\"text-break\"><code>/</code> 1\xa0GiB</li>", page)
        self.assertInHTML("<li class=\"text-break\"><code>/boot</code> not supported</li>", page)


class AgentFstrimTestCase(TransactionTestCase):
    def test_the_agent_answer_is_read_per_path(self):
        answer = {"paths": [{"path": "/", "trimmed": 4096, "minimum": 0}, {"path": "/boot", "error": "not supported"},
                            {"path": "C:\\"}, "garbage", {"trimmed": 1}]}
        dom = MagicMock()
        proxy = SimpleNamespace(instance=dom, ping_agent=lambda: None)
        with patch.object(vrt_instance, "qemuAgentCommand", return_value=json.dumps({"return": answer})) as command:
            paths = vrt_instance.wvmInstance.fstrim(proxy)
        self.assertEqual(paths, [{"path": "/", "trimmed": 4096, "error": None},
                                 {"path": "/boot", "trimmed": None, "error": "not supported"},
                                 {"path": "C:\\", "trimmed": None, "error": None}])
        self.assertEqual(command.call_args.args[2], vrt_instance.FSTRIM_TIMEOUT)  # not the 10 s of other agent calls
