"""An external snapshot of each VM chosen on the VM list, of one name: a
snapshot.create job each, with the VM page's rules (an owner with change
rights and the snapshot permission). A VM that is refused is named and the
others are queued."""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from lxml import html

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance
from operations.models import Operation
from vrtManager import util


class BulkSnapshotTestCase(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("bs-admin", "bs@example.com", "pw")
        self.client.force_login(self.admin)
        compute = Compute.objects.create(name="bs-host", hostname="127.0.0.1", login="", password="", type=4)
        self.vms = [Instance.objects.create(compute=compute, name=f"bs-vm{n}", uuid=f"00000000-0000-4000-8000-00000000020{n}")
                    for n in (1, 2)]
        # the VM's host is not this machine's libvirt: its last error would reach other tests
        proxy = self.proxy = MagicMock(**{"get_status.return_value": 5})
        proxy.instance.snapshotListNames.return_value = []
        proxy.check_external_snapshot.return_value = None
        patch.object(Instance, "proxy", property(lambda vm: proxy)).start()
        patch("instances.jobs._proxy", return_value=proxy).start()  # the snapshot job's own connection
        self.addCleanup(patch.stopall)

    def post(self, name, vms, user=None):
        if user:
            self.client.force_login(user)
        self.client.cookies.pop("messages", None)
        response = self.client.post(reverse("instances:bulk_snapshot"), {"snapshot_name": name, "vm": [vm.pk for vm in vms],
                                                                          "submission_key": "key-bulksnap1"})
        return response, [str(m) for m in get_messages(response.wsgi_request)]

    def test_a_job_for_each_vm(self):
        response, said = self.post("before-update", self.vms)
        self.assertRedirects(response, reverse("operations:jobs") + "?kind=snapshot.create", fetch_redirect_response=False)
        self.assertEqual(said, ["2 VMs are queued; the Jobs page follows them."])
        self.assertEqual(sorted(op.params["instance"] for op in Operation.objects.all()), [vm.pk for vm in self.vms])
        self.assertEqual({(op.kind, op.params["name"], op.params["external"], op.params["memory"], op.params["quiesce"])
                          for op in Operation.objects.all()}, {("snapshot.create", "before-update", True, False, False)})

    def test_a_wrong_name_is_refused(self):
        _response, said = self.post(".hidden", self.vms)
        self.assertTrue(said and not Operation.objects.exists(), said)
        _response, said = self.post("", self.vms)
        self.assertEqual(said, ["Choose the VMs and write the snapshot's name"])

    def test_an_owner_needs_the_snapshot_permission_and_change_rights(self):
        owner = get_user_model().objects.create_user("bs-owner", password="pw")
        UserInstance.objects.create(instance=self.vms[0], user=owner, is_change=True)
        UserInstance.objects.create(instance=self.vms[1], user=owner)  # no change rights
        _response, said = self.post("s1", self.vms, user=owner)
        self.assertEqual(said, ["bs-vm1: you may not snapshot it", "bs-vm2: you may not snapshot it"])
        self.assertFalse(Operation.objects.exists())
        owner.user_permissions.add(Permission.objects.get(codename="snapshot_instances"))
        _response, said = self.post("s1", self.vms, user=owner)
        self.assertEqual(said, ["bs-vm2: you may not snapshot it", "1 VM is queued; the Jobs page follows it."])
        self.assertEqual([(op.kind, op.params["instance"]) for op in Operation.objects.all()],
                         [("snapshot.create", self.vms[0].pk)])

    def test_a_vm_that_cannot_take_one_or_a_template_is_refused_when_asked(self):
        # what the snapshot reads before it is taken, refused before it is queued; a template not at all
        def check(name):
            raise util.OperationError("The VM has internal snapshots; external snapshots cannot be mixed with them")

        self.proxy.check_external_snapshot.side_effect = lambda name: None
        Instance.objects.filter(pk=self.vms[1].pk).update(is_template=True)
        _response, said = self.post("s1", self.vms)
        self.assertEqual(said, ["bs-vm2: a template's snapshots are not taken here", "1 VM is queued; the Jobs page follows it."])
        Operation.objects.all().delete()
        self.proxy.check_external_snapshot.side_effect = check
        _response, said = self.post("s2", self.vms[:1])
        self.assertEqual(said, ["bs-vm1: The VM has internal snapshots; external snapshots cannot be mixed with them"])
        self.assertFalse(Operation.objects.exists())

    def test_a_vm_one_does_not_see_is_not_told_a_template(self):
        # a template and a VM of no owner are refused alike: neither tells what it is
        Instance.objects.filter(pk=self.vms[1].pk).update(is_template=True)
        stranger = get_user_model().objects.create_user("bs-stranger", password="pw")
        stranger.user_permissions.add(Permission.objects.get(codename="snapshot_instances"))
        _response, said = self.post("s1", self.vms, user=stranger)
        self.assertEqual(said, ["a chosen VM: you may not snapshot it"] * 2)
        self.assertFalse(Operation.objects.exists())

    def test_the_box_is_for_one_who_may_snapshot_a_listed_vm(self):
        owner = get_user_model().objects.create_user("bs-owner2", password="pw")
        owner.user_permissions.add(Permission.objects.get(codename="snapshot_instances"))
        UserInstance.objects.create(instance=self.vms[0], user=owner)  # no change rights
        self.client.force_login(owner)
        with patch("instances.views.utils.vm_states", return_value={}), \
                patch("instances.views.refresh_instance_database"), patch("instances.views.utils.read_list_rows"):
            page = html.fromstring(self.client.get(reverse("instances:index")).content)
        self.assertFalse(page.xpath("//input[@name='snapshot_name']"))

    def test_the_list_offers_it(self):
        with patch("instances.views.utils.vm_states", return_value={}), \
                patch("instances.views.refresh_instance_database"), patch("instances.views.utils.read_list_rows"):
            page = html.fromstring(self.client.get(reverse("instances:index")).content)
        (form,) = page.xpath("//form[@id='bulk-power']")
        self.assertEqual(form.xpath(".//button[@value='snapshot']/@formaction"), [reverse("instances:bulk_snapshot")])
        self.assertTrue(form.xpath(".//input[@name='snapshot_name']"))
