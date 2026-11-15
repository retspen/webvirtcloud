"""Evacuating a host migrates its chosen VMs in one job, a migrate job each,
the chosen number at once; the page ticks the running VMs, leaves the
shut-off ones to choose and refuses a VM with a disk the two hosts do not
share. Migrations share the hosts, so the job's migrations are admitted
together; a create still waits for them."""

from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import etree, html
from appsettings.models import AppSettings
from computes.jobs import EvacuateHost
from operations import claims, jobs
from operations.models import Claim, Operation
from vrtManager import util

DOMAIN = """<domain type='test'><name>{name}</name><memory unit='MiB'>128</memory><vcpu>1</vcpu>
<os><type arch='i686'>hvm</type></os>{disk}</domain>"""
LOCAL = "<devices><disk type='file' device='disk'><source file='/local/{name}.img'/><target dev='vda'/></disk></devices>"


class EvacuateTests(TestCase):
    def setUp(self):
        self.conn = libvirt.open("test:///default")
        self.addCleanup(self.conn.close)
        self.compute = Compute.objects.create(name="ev", hostname="localhost", login="", password="", type=4)
        self.other = Compute.objects.create(name="ev-other", hostname="198.51.100.31", login="", password="", type=4)
        self.vms = {}
        for name, running, disk in (("ev-run", True, ""), ("ev-off", False, ""), ("ev-local", True, LOCAL)):
            domain = self.conn.defineXML(DOMAIN.format(name=name, disk=disk.format(name=name)))
            self.addCleanup(domain.undefine)
            if running:
                domain.create()
                self.addCleanup(domain.destroy)
            self.vms[name] = Instance.objects.create(compute=self.compute, name=name, uuid=domain.UUIDString())
        self.client.force_login(get_user_model().objects.create_superuser("ev-admin", "ev@example.com", "pw"))

    def page(self):
        def disk_plan(conn, xml):
            return [{"shared": "/local/" not in path} for path in etree.fromstring(xml).xpath("//source/@file")]

        with patch("vrtManager.connection.connection_manager.get_connection", return_value=self.conn), \
                patch("computes.views.utils.refresh_instance_database"), \
                patch("instances.jobs.migration_target"), \
                patch("computes.views.wvmInstances") as dest:
            dest.return_value.disk_plan.side_effect = disk_plan
            response = self.client.get(reverse("evacuate", args=[self.compute.id]))
        return html.fromstring(response.content)

    def box(self, page, name):
        (box,) = page.xpath("//input[@name='instance'][@value=$pk]", pk=str(self.vms[name].pk))
        return box

    def test_running_vms_are_ticked_and_shut_off_ones_left_to_choose(self):
        page = self.page()
        self.assertIsNotNone(self.box(page, "ev-run").get("checked"))
        off = self.box(page, "ev-off")
        self.assertIsNone(off.get("checked"))
        self.assertIsNotNone(off.get("data-shut-off"))

    def test_a_vm_with_a_disk_the_hosts_do_not_share_is_refused(self):
        page = self.page()
        local = self.box(page, "ev-local")
        self.assertIsNotNone(local.get("disabled"))
        self.assertIn("not on storage both hosts share", local.getparent().getparent().text_content())

    def evacuate(self, target, chosen):
        return self.client.post(reverse("evacuate", args=[self.compute.id]),
                                {"target": target, "instance": chosen, "parallel": "2", "submission_key": "evac0000key"})

    def test_the_chosen_vms_go_in_one_evacuation_job(self):
        chosen = [self.vms["ev-run"].pk, self.vms["ev-off"].pk]
        response = self.evacuate(self.other.pk, chosen)
        self.assertRedirects(response, reverse("instances", args=[self.compute.id]), fetch_redirect_response=False)
        (op,) = Operation.objects.all()
        self.assertEqual((op.kind, op.params), ("host.evacuate", {"compute": self.compute.pk, "target": self.other.pk,
                                                                  "parallel": 2, "instances": sorted(chosen)}))

    def test_a_destination_gone_since_the_form_was_shown_is_refused(self):
        gone = self.other.pk
        self.other.delete()
        self.assertEqual(self.evacuate(gone, [self.vms["ev-run"].pk]).status_code, 404)
        self.assertFalse(Operation.objects.exists())

    def test_a_host_with_no_other_host_says_so(self):
        self.other.delete()
        self.assertIn("There is no other host to migrate to.", self.page().text_content())


class Ctx:
    """The job context run uses, without a worker."""

    def __init__(self, op):
        self.op = op

    def record_intent(self, **values):
        self.op.intent = {**self.op.intent, **values}

    def set_phase(self, text):
        pass


class EvacuateJobTests(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="ej", hostname="192.0.2.40", login="", password="", type=4)
        self.other = Compute.objects.create(name="ej-other", hostname="192.0.2.41", login="", password="", type=4)
        self.vms = [Instance.objects.create(compute=self.compute, name=f"ej-{n}", uuid=f"00000000-0000-4000-8000-00000000000{n}")
                    for n in range(3)]
        self.admin = get_user_model().objects.create_superuser("ej-admin", "ej@example.com", "pw")
        patcher = patch("instances.jobs.MigrateInstance.validate")  # the hosts are not asked
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_job(self, parallel, ends):
        """Runs the evacuation of every VM; each round, ends(job) gives the end state of a running migration."""
        params = {"compute": self.compute.pk, "target": self.other.pk, "parallel": parallel,
                  "instances": [vm.pk for vm in self.vms]}
        op = Operation.objects.create(kind="host.evacuate", user=self.admin, username=self.admin.username,
                                      submission_key="key-evac0001", params=params,
                                      intent=EvacuateHost().plan(self.admin, params).intent)
        most = []

        def round_ends(seconds):
            running = Operation.objects.filter(kind="instance.migrate", state__in=Operation.ACTIVE)
            most.append(running.count())
            for job in running:
                job.state = ends(job)
                job.save()

        with patch("computes.jobs.time.sleep", side_effect=round_ends):
            try:
                return EvacuateHost().run(op, Ctx(op)), max(most)
            finally:
                self.migrations = Operation.objects.filter(kind="instance.migrate")

    def test_the_migrations_run_the_chosen_number_at_once(self):
        result, most = self.run_job(2, lambda job: Operation.SUCCEEDED)
        self.assertEqual((result, most), ({}, 2))
        self.assertEqual(sorted(job.params["instance"] for job in self.migrations), [vm.pk for vm in self.vms])

    def test_the_vms_that_did_not_migrate_are_named(self):
        fail = self.vms[1].pk
        with self.assertRaisesRegex(util.OperationError, "did not migrate"):
            self.run_job(1, lambda job: Operation.FAILED if job.params["instance"] == fail else Operation.SUCCEEDED)
        self.assertEqual(self.migrations.count(), 3)

    def test_a_create_waits_for_the_migrations(self):
        Operation.objects.all().delete()
        jobs.submit("instance.migrate", self.admin, {"instance": self.vms[0].pk, "target": self.other.pk}, "key-mig00001")
        jobs.submit("instance.migrate", self.admin, {"instance": self.vms[1].pk, "target": self.other.pk}, "key-mig00002")
        with self.assertRaises(claims.Busy):
            claims.admit({claims.reconcile_key(self.compute.pk): Claim.EXCLUSIVE}, holder="test")

    def test_a_vm_that_left_the_host_meanwhile_stays_where_it_went(self):
        third = Compute.objects.create(name="ej-third", hostname="192.0.2.42", login="", password="", type=4)
        left = self.vms[2]

        def ends(job):  # while the first migrations run, the last VM is moved to a third host
            Instance.objects.filter(pk=left.pk).update(compute=third)
            return Operation.SUCCEEDED

        self.run_job(1, ends)
        self.assertNotIn(left.pk, [job.params["instance"] for job in self.migrations])

    def test_one_evacuation_runs_at_a_time(self):
        raw = {"compute": self.compute.pk, "target": self.other.pk, "parallel": 1, "instances": [self.vms[0].pk]}
        jobs.submit("host.evacuate", self.admin, raw, "key-evac0002")
        with self.assertRaises(claims.Busy):
            jobs.submit("host.evacuate", self.admin, {**raw, "compute": self.other.pk, "target": self.compute.pk},
                        "key-evac0003")

    def test_a_host_changed_meanwhile_stops_the_evacuation(self):
        def ends(job):
            Compute.objects.filter(pk=self.other.pk).update(hostname="192.0.2.99")
            return Operation.SUCCEEDED

        with self.assertRaisesRegex(util.OperationError, "changed or deleted"):
            self.run_job(1, ends)
        self.assertEqual(self.migrations.count(), 1)

    def test_a_worker_lowered_to_one_slot_stops_the_evacuation(self):
        def ends(job):
            AppSettings.objects.filter(key="WORKER_CONCURRENCY").update(value="1")
            return Operation.SUCCEEDED

        with self.assertRaisesRegex(util.OperationError, "one job at a time"):
            self.run_job(1, ends)
        self.assertEqual(self.migrations.count(), 1)

    def test_a_busy_vm_lets_the_others_go_first(self):
        held = claims.admit({claims.instance_key(self.vms[0].uuid): Claim.EXCLUSIVE}, holder=claims.holder_id())

        def ends(job):
            Claim.objects.filter(pk__in=held).delete()  # the short operation on the first VM ends
            return Operation.SUCCEEDED

        self.run_job(1, ends)
        order = [job.params["instance"] for job in self.migrations.order_by("created_at")]
        self.assertEqual(order, [self.vms[1].pk, self.vms[2].pk, self.vms[0].pk])

    def test_a_vm_an_uncertain_job_holds_is_not_waited_for(self):
        stuck = Operation.objects.create(kind="instance.migrate", user=self.admin, username=self.admin.username,
                                         submission_key="key-stuck001", state=Operation.UNCERTAIN)
        Claim.objects.create(operation=stuck, resource=claims.instance_key(self.vms[0].uuid), mode=Claim.EXCLUSIVE)
        with self.assertRaisesRegex(util.OperationError, "did not migrate"):
            self.run_job(2, lambda job: Operation.SUCCEEDED)
        self.assertEqual(self.migrations.exclude(pk=stuck.pk).count(), 2)

    def test_a_migration_from_a_host_the_vm_left_is_refused(self):
        third = Compute.objects.create(name="ej-third", hostname="192.0.2.42", login="", password="", type=4)
        raw = {"instance": self.vms[0].pk, "source": third.pk, "target": self.other.pk}
        with self.assertRaisesRegex(util.OperationError, "moved to another compute"):
            jobs.submit("instance.migrate", self.admin, raw, "key-mig00003")
