"""The Schedules pages: add, edit, delete a backup schedule; its runs."""

import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from lxml import html as lxml_html

from computes.models import Compute, Tag
from instances.models import Instance
from instances.tests.test_page_controls import PageControls
from logs.models import Logs
from operations.models import Operation
from operations.utils import say
from vmbackups.models import Backup, BackupPolicy, BackupRun, BackupTarget, BackupTargetPool


class PolicyPageTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("pp_admin", "a@example.com", "pw")
        self.client.force_login(self.admin)
        self.c1 = Compute.objects.create(name="h1", hostname="192.0.2.81", login="u", password="p", type=1)
        self.c2 = Compute.objects.create(name="h2", hostname="192.0.2.82", login="u", password="p", type=1)
        self.vm1 = Instance.objects.create(compute=self.c1, name="vm1", uuid="81818181-0000-4000-8000-000000000001")
        self.vm3 = Instance.objects.create(compute=self.c2, name="vm3", uuid="81818181-0000-4000-8000-000000000003")
        self.target = BackupTarget.objects.create(name="nfs1")
        BackupTargetPool.objects.create(target=self.target, compute=self.c1, pool="b1", pool_uuid="u")

    def post(self, **fields):
        data = {"name": "nightly", "target": self.target.pk, "time": "02:00", "keep": "7", "keep_weekly": "0", "keep_monthly": "0",
                "full_every": "1", "enabled": "on",
                **fields}
        return self.client.post(reverse("vmbackups:policy_new"), data)

    def test_a_schedule_of_chosen_vms(self):
        response = self.post(scope="instances", instances=[self.vm1.pk])
        policy = BackupPolicy.objects.get()
        # back to the list, which says it is saved: the schedule's page is its edit form
        self.assertRedirects(response, reverse("vmbackups:policies"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("vmbackups:policies")), "Backup schedule nightly is saved.")
        self.assertEqual((list(policy.instances.all()), policy.compute, policy.time, policy.keep, policy.owner),
                         ([self.vm1], None, datetime.time(2), 7, self.admin))
        self.assertTrue(Logs.objects.filter(message__contains="Backup schedule nightly").exists())

    def test_a_schedule_of_a_compute(self):
        self.post(scope="compute", compute=self.c1.pk)
        self.assertEqual(BackupPolicy.objects.get().compute, self.c1)

    def test_a_schedule_of_a_tag(self):
        prod = Tag.objects.create(name="prod")
        self.vm1.tags.add(prod)
        self.post(scope="tag", tag=prod.pk)
        self.assertEqual(BackupPolicy.objects.get().tag, prod)
        self.assertContains(self.client.get(reverse("vmbackups:policies")), "VMs tagged prod")

    def test_the_vms_chosen_are_those_of_the_scope_only(self):
        prod = Tag.objects.create(name="prod")
        for fields in ({}, {"scope": "compute"}, {"scope": "tag", "compute": self.c1.pk}):
            with self.subTest(fields):
                response = self.post(**fields)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Choose the VMs to back up" if fields else "This field is required")
        self.assertFalse(BackupPolicy.objects.exists())
        # a VM gone from another scope's (hidden) field is no error
        self.post(scope="compute", compute=self.c1.pk, instances=[99999])
        self.assertEqual(BackupPolicy.objects.get().compute, self.c1)
        BackupPolicy.objects.all().delete()
        # a choice left in another scope's field is not saved
        self.post(scope="instances", instances=[self.vm1.pk], compute=self.c1.pk, tag=prod.pk)
        policy = BackupPolicy.objects.get()
        self.assertEqual((list(policy.instances.all()), policy.compute, policy.tag), ([self.vm1], None, None))

    def test_vms_on_a_host_without_the_target_are_refused(self):
        response = self.post(scope="instances", instances=[self.vm3.pk])
        self.assertContains(response, "has no storage pool on h2")
        response = self.post(scope="compute", compute=self.c2.pk)
        self.assertContains(response, "has no storage pool on h2")
        prod = Tag.objects.create(name="prod")
        self.vm3.tags.add(prod)
        self.assertContains(self.post(scope="tag", tag=prod.pk), "has no storage pool on h2")  # the tag's VMs now
        self.assertFalse(BackupPolicy.objects.exists())

    def test_the_list_leads_to_the_new_schedule_page(self):
        from lxml import html as lxml_html

        page = lxml_html.fromstring(self.client.get(reverse("vmbackups:policies")).content)
        self.assertEqual(page.xpath("//a[@href=$u]/@href", u=reverse("vmbackups:policy_new")), [reverse("vmbackups:policy_new")])
        self.assertFalse(page.xpath("//div[@role='main']//form[@method='post']"))  # no form on the list
        new = lxml_html.fromstring(self.client.get(reverse("vmbackups:policy_new")).content)
        self.assertTrue(new.xpath("//input[@name='name']"))

    def test_keep_and_full_every_at_least_one(self):
        self.assertEqual(self.post(scope="instances", instances=[self.vm1.pk], keep="0").status_code, 200)
        self.assertEqual(self.post(scope="instances", instances=[self.vm1.pk], full_every="0").status_code, 200)
        self.assertFalse(BackupPolicy.objects.exists())
        self.post(scope="instances", instances=[self.vm1.pk], full_every="7")
        self.assertEqual(BackupPolicy.objects.get().full_every, 7)

    def schedule(self):
        policy = BackupPolicy.objects.create(name="nightly", target=self.target, time=datetime.time(2), keep=7,
                                             owner=self.admin)
        policy.instances.add(self.vm1)
        return policy

    def test_edit_and_the_runs(self):
        policy = self.schedule()
        BackupRun.objects.create(policy=policy, instance=self.vm1, day=datetime.date.today(), state=BackupRun.SKIPPED,
                                 note=say("The host was in maintenance"))
        url = reverse("vmbackups:policy", args=[policy.pk])
        page = self.client.get(url)
        self.assertContains(page, "The host was in maintenance")
        self.client.post(url, {"name": "nightly", "target": self.target.pk, "time": "03:30", "keep": "3", "keep_weekly": "4",
                               "keep_monthly": "6", "full_every": "1", "scope": "instances", "instances": [self.vm1.pk]})
        policy.refresh_from_db()
        self.assertEqual((policy.time, policy.keep, policy.keep_weekly, policy.keep_monthly, policy.enabled),
                         (datetime.time(3, 30), 3, 4, 6, False))
        page = self.client.get(reverse("vmbackups:policies"))
        self.assertContains(page, "Backup schedule nightly is saved.")
        self.assertContains(page, "3 + 4 weekly + 6 monthly")

    def add_run(self, policy, vm, days_ago, state=BackupRun.SUBMITTED, job_state=None, note=(), job_error=()):
        day = datetime.date.today() - datetime.timedelta(days=days_ago)
        job = job_state and Operation.objects.create(kind="backup.create", username="pp_admin", submission_key=f"{vm.pk}-{day}",
                                                     resource="r", state=job_state, error=list(job_error))
        return BackupRun.objects.create(policy=policy, instance=vm, day=day, state=state, operation=job, note=list(note))

    def test_the_runs_of_the_last_14_days(self):
        policy = self.schedule()
        self.add_run(policy, self.vm1, 0, job_state=Operation.SUCCEEDED)
        failed = self.add_run(policy, self.vm1, 1, job_state=Operation.FAILED, job_error=say("The guest agent did not answer"))
        self.add_run(policy, self.vm1, 2, BackupRun.SKIPPED, note=say("The host was in maintenance"))
        self.add_run(policy, self.vm1, 14, BackupRun.FAILED)  # before the 14 days
        self.add_run(policy, self.vm1, -1, BackupRun.FAILED)  # after them: the time zone moved west
        self.add_run(policy, self.vm3, 3, job_state=Operation.SUCCEEDED)  # a VM the schedule no longer backs up
        page = lxml_html.fromstring(self.client.get(reverse("vmbackups:policy", args=[policy.pk])).content)
        rows = page.xpath("//table[contains(@class, 'run-grid')]/tbody/tr")
        self.assertEqual([row.xpath("string(th)") for row in rows], ["vm1", "vm3"])
        marks = [mark.get("class").split()[1] for mark in rows[0].xpath(".//*[contains(@class, 'run-mark')]")]
        self.assertEqual(marks, ["run-none"] * 11 + ["run-skipped", "run-failed", "run-succeeded"])
        self.assertEqual(rows[0].xpath(".//a[contains(@class, 'run-failed')]/@href"),
                         [reverse("operations:job", args=[failed.operation_id])])
        problems = [" ".join(item.text_content().split()) for item in page.xpath("//ul[@id='run-problems']/li")]
        self.assertEqual(len(problems), 2)
        self.assertIn("vm1 Failed: The guest agent did not answer", problems[0])
        self.assertIn("vm1 Skipped: The host was in maintenance", problems[1])

    def test_the_list_marks_a_day_by_its_worst_run(self):
        policy = self.schedule()
        policy.instances.add(self.vm3)
        self.add_run(policy, self.vm1, 1, job_state=Operation.SUCCEEDED)
        self.add_run(policy, self.vm3, 1, job_state=Operation.FAILED)
        self.add_run(policy, self.vm1, 0, job_state=Operation.RUNNING)
        self.add_run(policy, self.vm3, 0, job_state=Operation.SUCCEEDED)
        page = lxml_html.fromstring(self.client.get(reverse("vmbackups:policies")).content)
        strip = page.xpath("//a[contains(@class, 'run-days')]")  # one link to the schedule, for touch and keyboard
        self.assertEqual(strip[0].get("href"), reverse("vmbackups:policy", args=[policy.pk]))
        marks = strip[0].xpath("./span")
        self.assertEqual(len(marks), 14)
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        self.assertEqual((marks[-2].get("class"), marks[-2].get("title")),
                         ("run-mark run-failed", f"{yesterday}: 1 failed, 1 backed up"))
        self.assertEqual(marks[-1].get("class"), "run-mark run-running")
        self.assertTrue(marks[-1].get("title").endswith(": 1 running, 1 backed up"))
        self.assertEqual(marks[0].get("class"), "run-mark run-none")

    def test_delete_keeps_the_backups(self):
        policy = self.schedule()
        backup = Backup.objects.create(target=self.target, instance=self.vm1, vm_uuid=self.vm1.uuid, vm_name="vm1",
                                       compute_name="h1", state=Backup.READY, policy=policy)
        response = self.client.post(reverse("vmbackups:policy", args=[policy.pk]), {"delete": "1"})
        self.assertRedirects(response, reverse("vmbackups:policies"), fetch_redirect_response=False)
        self.assertFalse(BackupPolicy.objects.exists())
        self.assertTrue(Backup.objects.filter(pk=backup.pk, policy=None).exists())
        self.assertContains(self.client.get(reverse("vmbackups:policies")), "Backup schedule nightly is deleted")

    def test_the_list_and_the_backups_page(self):
        policy = self.schedule()
        Backup.objects.create(target=self.target, instance=self.vm1, vm_uuid=self.vm1.uuid, vm_name="vm1",
                              compute_name="h1", state=Backup.MISSING, policy=policy)
        page = lxml_html.fromstring(self.client.get(reverse("vmbackups:policies")).content)
        self.assertIn("nightly", page.xpath("string(//table)"))
        index = lxml_html.fromstring(self.client.get(reverse("vmbackups:index")).content)
        row = index.xpath("string(//table[@id='backups']/tbody/tr)")
        self.assertIn("nightly", row)
        self.assertIn("Missing", row)
        self.assertFalse(index.xpath("//a[contains(@href, '/restore/')]"))  # a missing backup is not restored
        self.assertNotIn("Incremental", row)
        Backup.objects.create(target=self.target, instance=self.vm1, vm_uuid=self.vm1.uuid, vm_name="vm1",
                              compute_name="h1", state=Backup.READY, policy=policy, parent=Backup.objects.get())
        index = lxml_html.fromstring(self.client.get(reverse("vmbackups:index")).content)
        self.assertIn("Incremental", " ".join(index.xpath("//table[@id='backups']/tbody/tr/td//text()")))

    def test_a_target_with_a_schedule_is_not_deleted(self):
        self.schedule()
        url = reverse("vmbackups:target", args=[self.target.pk])
        from django.contrib.messages import get_messages

        response = self.client.post(url, {"delete": "1"})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        self.assertIn("Backup target nfs1 has schedules; delete them first",
                      [str(m) for m in get_messages(response.wsgi_request)])
        self.assertTrue(BackupTarget.objects.filter(pk=self.target.pk).exists())

    def test_only_superusers(self):
        policy = self.schedule()
        get_user_model().objects.create_user("pp_user", password="pw")
        self.client.force_login(get_user_model().objects.get(username="pp_user"))
        self.assertEqual(self.client.get(reverse("vmbackups:policies")).status_code, 403)
        self.assertEqual(self.client.get(reverse("vmbackups:policy", args=[policy.pk])).status_code, 403)


class PolicyTabTests(PageControls, TestCase):
    def test_the_vm_tab_names_its_schedules(self):
        admin = get_user_model().objects.create_superuser("pt-admin", "a@example.com", "x")
        target = BackupTarget.objects.create(name="nfs1")
        BackupTargetPool.objects.create(target=target, compute=self.compute, pool="b1", pool_uuid="u")
        chosen = BackupPolicy.objects.create(name="chosen", target=target, time=datetime.time(2), keep=2, owner=admin)
        chosen.instances.add(self.instance)
        BackupPolicy.objects.create(name="whole-host", target=target, compute=self.compute, time=datetime.time(3), keep=2,
                                    owner=admin)
        prod = Tag.objects.create(name="prod")
        self.instance.tags.add(prod)
        BackupPolicy.objects.create(name="tagged", target=target, tag=prod, time=datetime.time(4), keep=2, owner=admin)
        with patch("vmbackups.utils.wvmBackup"):
            self.controls(admin)
        tab = lxml_html.fromstring(self.last_page).xpath("string(//div[@id='backups'])")
        self.assertIn("chosen", tab)
        self.assertIn("whole-host", tab)
        self.assertIn("tagged", tab)
