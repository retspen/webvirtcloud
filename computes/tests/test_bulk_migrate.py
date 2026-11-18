"""Bulk migrating a host migrates its chosen VMs in one job, a migrate job each,
the chosen number at once; the page ticks the running VMs, leaves the
shut-off ones to choose and refuses a VM with a disk the two hosts do not
share. Migrations share the hosts, so the job's migrations are admitted
together; a create still waits for them."""

from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import html
from appsettings.models import AppSettings
from computes.jobs import BulkMigrate
from operations import claims, jobs
from operations.models import Claim, Operation
from vrtManager import util

DOMAIN = """<domain type='test'><name>{name}</name><memory unit='MiB'>128</memory><vcpu>1</vcpu>
<os><type arch='i686'>hvm</type></os>{disk}</domain>"""
LOCAL = "<devices><disk type='file' device='disk'><source file='/local/{name}.img'/><target dev='vda'/></disk></devices>"


class BulkMigratePageTests(TestCase):
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

    def page(self, **query):
        with patch("vrtManager.connection.connection_manager.get_connection", return_value=self.conn), \
                patch("computes.views.utils.refresh_instance_database"), \
                patch("instances.jobs.migration_target"), \
                patch("computes.reach.wvmInstances") as dest:
            dest.return_value.shares.side_effect = lambda conn, directory: directory != "/local"
            response = self.client.get(reverse("bulk_migrate", args=[self.compute.id]), query)
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

    def test_the_vms_tags_choose_them(self):
        from computes.models import Tag
        self.vms["ev-run"].tags.add(Tag.objects.create(name="prod"), Tag.objects.create(name="web"))
        page = self.page()
        self.assertEqual(page.xpath("//select[@id='bulk-migrate-tag']/option/@value"), ["", "prod", "web"])
        self.assertEqual(self.box(page, "ev-run").get("data-tags"), "prod web")
        self.assertEqual(self.box(page, "ev-off").get("data-tags"), "")

    def test_a_vm_with_a_disk_the_hosts_do_not_share_is_refused(self):
        page = self.page()
        local = self.box(page, "ev-local")
        self.assertIsNotNone(local.get("disabled"))
        self.assertIn("not on storage both hosts share", local.getparent().getparent().text_content())

    def test_a_host_in_maintenance_is_no_destination(self):
        Compute.objects.create(name="ev-rest", hostname="198.51.100.32", login="", password="", type=4, maintenance_since=timezone.now())
        page = self.page()
        self.assertEqual(page.xpath("//select[@id='bulk-migrate-target']"), [])  # one destination left: no choice
        self.assertNotIn("ev-rest", page.text_content())

    def bulk_migrate(self, target, chosen):
        return self.client.post(reverse("bulk_migrate", args=[self.compute.id]),
                                {"target": target, "instance": chosen, "parallel": "2", "submission_key": "evac0000key"})

    def test_the_chosen_vms_go_in_one_bulk_migration_job(self):
        chosen = [self.vms["ev-run"].pk, self.vms["ev-off"].pk]
        response = self.bulk_migrate(self.other.pk, chosen)
        self.assertRedirects(response, reverse("instances", args=[self.compute.id]), fetch_redirect_response=False)
        (op,) = Operation.objects.all()
        self.assertEqual((op.kind, op.params), ("host.bulk_migrate", {
            "compute": self.compute.pk, "parallel": 2, "moves": [[pk, self.other.pk] for pk in sorted(chosen)],
            "maintenance": False}))

    def test_a_destination_gone_since_the_form_was_shown_is_refused(self):
        gone = self.other.pk
        self.other.delete()
        self.assertEqual(self.bulk_migrate(gone, [self.vms["ev-run"].pk]).status_code, 404)
        self.assertFalse(Operation.objects.exists())

    def test_one_destination_is_named_and_several_are_a_choice(self):
        self.assertEqual(self.page().xpath("//select[@name='target']"), [])
        self.assertIn("ev-other", self.page().xpath("//div[contains(@class, 'card-header')]/span/text()"))
        Compute.objects.create(name="ev-third", hostname="198.51.100.32", login="", password="", type=4)
        self.assertEqual(self.page().xpath("//select[@name='target']/option/text()"),
                         ["Spread over the other hosts", "ev-other", "ev-third"])

    def spread(self, page):
        """{VM name: the host it goes to} of the migrations the page would run."""
        names = {str(vm.pk): name for name, vm in self.vms.items()}
        hosts = {str(host.pk): host.name for host in Compute.objects.all()}
        (form,) = page.xpath("//form[contains(@class, 'card')]")
        return {names[vm]: hosts[target] for vm, target in zip(form.xpath(".//input[@name='instance']/@value"),
                                                               form.xpath(".//input[@name='target']/@value"))}

    def test_with_several_hosts_the_vms_spread_over_them(self):
        Compute.objects.create(name="ev-third", hostname="198.51.100.32", login="", password="", type=4)
        self.assertEqual(self.spread(self.page()), {"ev-run": "ev-other"})
        both = [self.vms["ev-run"].pk, self.vms["ev-off"].pk]
        # a shut-off VM ticked goes too, to the host the running one left emptier
        self.assertEqual(self.spread(self.page(shown=both, vm=both)), {"ev-run": "ev-other", "ev-off": "ev-third"})
        # one unticked stays
        self.assertEqual(self.spread(self.page(shown=both, vm=both[1:])), {"ev-off": "ev-other"})

    def test_the_vms_spread_also_when_this_hosts_capacity_cannot_be_read(self):
        Compute.objects.create(name="ev-third", hostname="198.51.100.32", login="", password="", type=4)
        real = Compute.capacity.func

        def capacity(host):
            return None if host.pk == self.compute.pk else real(host)

        with patch.object(Compute, "capacity", property(capacity)):
            self.assertEqual(self.spread(self.page()), {"ev-run": "ev-other"})

    def test_spread_vms_go_in_one_bulk_migration_job_with_their_hosts(self):
        third = Compute.objects.create(name="ev-third", hostname="198.51.100.32", login="", password="", type=4)
        run, off = self.vms["ev-run"].pk, self.vms["ev-off"].pk
        response = self.client.post(reverse("bulk_migrate", args=[self.compute.id]),
                                    {"spread": "1", "instance": [run, off], "target": [self.other.pk, third.pk],
                                     "parallel": "2", "submission_key": "evac0000spr"})
        self.assertRedirects(response, reverse("instances", args=[self.compute.id]), fetch_redirect_response=False)
        (op,) = Operation.objects.all()
        self.assertEqual(op.params["moves"], sorted([[run, self.other.pk], [off, third.pk]]))
        self.assertEqual(op.resource_label, "ev -> ev-other, ev-third")

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


class BulkMigrateJobTests(TestCase):
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
        """Runs the bulk migration of every VM; each round, ends(job) gives the end state of a running migration."""
        params = {"compute": self.compute.pk, "parallel": parallel, "moves": [[vm.pk, self.other.pk] for vm in self.vms]}
        op = Operation.objects.create(kind="host.bulk_migrate", user=self.admin, username=self.admin.username,
                                      submission_key="key-evac0001", params=params,
                                      intent=BulkMigrate().plan(self.admin, params).intent)
        most = []

        def round_ends(seconds):
            running = Operation.objects.filter(kind="instance.migrate", state__in=Operation.ACTIVE)
            most.append(running.count())
            for job in running:
                job.state = ends(job)
                job.save()

        self.op = op
        with patch("computes.jobs.time.sleep", side_effect=round_ends):
            try:
                return BulkMigrate().run(op, Ctx(op)), max(most)
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
        # the worker hands a failed job that made changes to recovery: it adds no "stopped" message
        outcome = BulkMigrate().reconcile(self.op)
        self.assertEqual((outcome.state, outcome.error), (Operation.FAILED, []))

    def test_a_bulk_migration_the_worker_left_says_it_stopped(self):
        op = Operation(kind="host.bulk_migrate", intent={"migrations": {}})
        self.assertIn("stopped", BulkMigrate().reconcile(op).error[0]["text"])

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

    def test_one_bulk_migration_runs_at_a_time(self):
        raw = {"compute": self.compute.pk, "parallel": 1, "moves": [[self.vms[0].pk, self.other.pk]]}
        jobs.submit("host.bulk_migrate", self.admin, raw, "key-evac0002")
        with self.assertRaises(claims.Busy):
            jobs.submit("host.bulk_migrate", self.admin,
                        {**raw, "compute": self.other.pk, "moves": [[self.vms[0].pk, self.compute.pk]]}, "key-evac0003")

    def test_a_host_changed_meanwhile_stops_the_bulk_migration(self):
        def ends(job):
            Compute.objects.filter(pk=self.other.pk).update(hostname="192.0.2.99")
            return Operation.SUCCEEDED

        with self.assertRaisesRegex(util.OperationError, "changed or deleted"):
            self.run_job(1, ends)
        self.assertEqual(self.migrations.count(), 1)

    def test_a_worker_lowered_to_one_slot_stops_the_bulk_migration(self):
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

    def test_the_host_page_shows_the_bulk_migration_and_not_its_migrations(self):
        params = {"compute": self.compute.pk, "parallel": 2, "moves": [[self.vms[0].pk, self.other.pk]]}
        bulk = jobs.submit("host.bulk_migrate", self.admin, params, "key-bulk0001")
        child = jobs.submit("instance.migrate", self.admin, {"instance": self.vms[0].pk, "target": self.other.pk},
                            "key-mig00004", parent=bulk)
        self.client.force_login(self.admin)

        def shown(key):
            return [job["id"] for job in self.client.get(reverse("operation-resource"), {"key": key}).json()["jobs"]]

        self.assertEqual(shown(claims.compute_key(self.compute.pk)), [str(bulk.pk)])
        self.assertEqual(shown(claims.instance_key(self.vms[0].uuid)), [str(child.pk)])
        self.assertEqual(BulkMigrate().progress(bulk), (0, 1))
