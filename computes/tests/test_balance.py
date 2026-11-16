"""Balance proposes migrations of running VMs that even out the memory, then
the vCPUs, the hosts give their running VMs, and runs the proposal shown in
one job of migrate jobs that take only a running VM."""

from unittest.mock import patch

import libvirt
from computes.balance import propose
from computes.jobs import Balance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import etree, html
from operations import claims, jobs
from operations.models import Operation

DOMAIN = """<domain type='test'><name>{name}</name><memory unit='MiB'>128</memory><vcpu>1</vcpu>
<os><type arch='i686'>hvm</type></os>{disk}</domain>"""
LOCAL = "<devices><disk type='file' device='disk'><source file='/local/{name}.img'/><target dev='vda'/></disk></devices>"
ROOM = {"a": 100, "b": 100, "c": 100, "d": 100}


class ProposeTests(SimpleTestCase):
    def test_moves_even_out_the_memory_also_past_a_plateau_of_the_spread(self):
        # the largest minus the smallest load stays 10 after the first move; the sum of squares does not
        loads = {"a": (10, 0), "b": (10, 0), "c": (0, 0), "d": (0, 0)}
        vms = [(1, "a", 5, 0, {"b", "c", "d"}), (2, "a", 5, 0, {"b", "c", "d"}),
               (3, "b", 5, 0, {"a", "c", "d"}), (4, "b", 5, 0, {"a", "c", "d"})]
        moves, after = propose(loads, vms, ROOM)
        self.assertEqual(len(moves), 2)
        self.assertEqual(sorted(load[0] for load in after.values()), [5, 5, 5, 5])

    def test_the_memory_comes_first_then_the_vcpus(self):
        loads = {"a": (8, 2), "b": (0, 6)}
        vms = [(1, "a", 4, 1, {"b"}), (2, "b", 0, 3, {"a"})]
        moves, after = propose(loads, vms, ROOM)
        self.assertEqual(moves, [(1, "a", "b"), (2, "b", "a")])
        self.assertEqual(after, {"a": [4, 4], "b": [4, 4]})

    def test_a_vm_moves_once_and_only_where_it_may_go(self):
        loads = {"a": (12, 0), "b": (0, 0), "c": (0, 0)}
        moves, _after = propose(loads, [(1, "a", 6, 0, {"b"}), (2, "a", 6, 0, {"b"})], ROOM)
        self.assertEqual(moves, [(1, "a", "b")])

    def test_no_move_fills_a_host_past_its_room(self):
        loads = {"a": (60, 0), "b": (50, 0)}
        self.assertEqual(propose(loads, [(1, "a", 30, 0, {"b"})], {"a": 40, "b": 20}), ([], {"a": [60, 0], "b": [50, 0]}))

    def test_a_vm_moved_away_makes_no_room_for_one_moved_in(self):
        # b's room stays 0 after vm 2 leaves it: vm 1 would fill b before vm 2 has left, if it ran first
        loads = {"a": (100, 0), "b": (80, 0), "c": (0, 0)}
        vms = [(1, "a", 30, 0, {"b"}), (2, "b", 40, 0, {"c"})]
        self.assertEqual(propose(loads, vms, {"a": 0, "b": 0, "c": 100})[0], [(2, "b", "c")])

    def test_small_vms_move_rather_than_a_large_one_for_the_same_balance(self):
        # a: a large VM (16) and two small ones (1, 2); b: one small VM (1). Moving the large VM to b and
        # the small one back ends as even as moving the two small ones, which moves far less memory
        loads = {"a": (19, 7), "b": (1, 4)}
        vms = [(1, "a", 16, 2, {"b"}), (2, "a", 1, 1, {"b"}), (3, "a", 2, 4, {"b"}), (4, "b", 1, 4, {"a"})]
        moves, after = propose(loads, vms, ROOM)
        self.assertEqual(moves, [(2, "a", "b"), (3, "a", "b")])
        self.assertEqual(after, {"a": [16, 2], "b": [4, 9]})

    def test_a_large_vm_moves_when_only_it_evens_out_the_hosts(self):
        loads = {"a": (20, 0), "b": (0, 0)}
        vms = [(1, "a", 10, 0, {"b"}), (2, "a", 1, 0, {"b"})]
        self.assertEqual(propose(loads, vms, {"a": 100, "b": 100})[0], [(1, "a", "b")])

    def test_even_hosts_need_no_move(self):
        loads = {"a": (4, 2), "b": (4, 2)}
        self.assertEqual(propose(loads, [(1, "a", 4, 2, {"b"})], ROOM)[0], [])


class BalancePageTests(TestCase):
    def setUp(self):
        self.conn = libvirt.open("test:///default")
        self.addCleanup(self.conn.close)
        self.compute = Compute.objects.create(name="ba", hostname="localhost", login="", password="", type=4)
        self.other = Compute.objects.create(name="ba-other", hostname="198.51.100.41", login="", password="", type=4)
        self.vms = {}
        for name, running, disk in (("ba-1", True, ""), ("ba-2", True, ""), ("ba-off", False, ""),
                                    ("ba-local", True, LOCAL)):
            domain = self.conn.defineXML(DOMAIN.format(name=name, disk=disk.format(name=name)))
            self.addCleanup(domain.undefine)
            if running:
                domain.create()
                self.addCleanup(domain.destroy)
            self.vms[name] = Instance.objects.create(compute=self.compute, name=name, uuid=domain.UUIDString())
        self.client.force_login(get_user_model().objects.create_superuser("ba-admin", "ba@example.com", "pw"))

    def page(self, **query):
        def disk_plan(conn, xml):
            return [{"shared": "/local/" not in path} for path in etree.fromstring(xml).xpath("//source/@file")]

        with patch("vrtManager.connection.connection_manager.get_connection", return_value=self.conn), \
                patch("computes.views.utils.refresh_instance_database"), \
                patch("instances.jobs.migration_target"), \
                patch("computes.views.wvmInstances") as dest:
            dest.return_value.disk_plan.side_effect = disk_plan
            self.response = self.client.get(reverse("balance"), query)
        return html.fromstring(self.response.content)

    def moved(self, page):
        return page.xpath("//form[@method='post']//input[@name='instance']/@value")

    def test_a_running_vm_moves_to_the_emptier_host(self):
        page = self.page()
        self.assertEqual(self.moved(page), [str(self.vms["ba-1"].pk)])
        self.assertEqual(page.xpath("//form[@method='post']//input[@name='target']/@value"), [str(self.other.pk)])

    def test_a_vm_unticked_stays_and_another_moves_instead(self):
        pk = str(self.vms["ba-1"].pk)
        page = self.page(shown=pk)
        self.assertEqual(self.moved(page), [str(self.vms["ba-2"].pk)])
        (box,) = page.xpath("//input[@name='vm'][@value=$pk]", pk=pk)
        self.assertIsNone(box.get("checked"))  # listed to tick again
        self.assertEqual(self.moved(self.page(shown=pk, vm=pk)), [pk])

    def test_a_vm_with_a_disk_the_hosts_do_not_share_cannot_move_and_still_counts(self):
        page = self.page()
        (row,) = [row for row in page.xpath("//tr") if "ba-local" in row.text_content()]
        self.assertIn("not on storage both hosts share", row.text_content())
        host = next(host for host in self.response.context["hosts"] if host == self.compute)
        self.assertEqual(host.before, [3 * 128 * 1024, 3])  # the shut-off VM is not counted
        self.assertNotIn(str(self.vms["ba-off"].pk), page.xpath("//input[@name='vm' or @name='instance']/@value"))

    def test_a_host_that_does_not_answer_is_left_out(self):
        def read_hosts(computes):
            for compute in computes:
                compute.status, compute.shown_capacity = (False, None) if compute == self.other else (True, compute.capacity)

        with patch("computes.views.read_hosts", side_effect=read_hosts):
            page = self.page()
        self.assertEqual(self.moved(page), [])
        self.assertIn("ba-other", page.xpath("//div[contains(@class, 'alert-warning')]")[0].text_content())

    def test_the_moves_shown_go_in_one_balance_job(self):
        vm = self.vms["ba-1"].pk
        response = self.client.post(reverse("balance"), {"instance": [vm], "source": [self.compute.pk],
                                                          "target": [self.other.pk], "parallel": "1",
                                                          "submission_key": "bal00000key"})
        self.assertRedirects(response, reverse("computes"), fetch_redirect_response=False)
        (op,) = Operation.objects.all()
        self.assertEqual((op.kind, op.params, op.resource),
                         ("host.balance", {"parallel": 1, "moves": [[vm, self.compute.pk, self.other.pk]]},
                          claims.bulk_migrate_key()))


class Ctx:
    """The job context run uses, without a worker."""

    def __init__(self, op):
        self.op = op

    def record_intent(self, **values):
        self.op.intent = {**self.op.intent, **values}

    def set_phase(self, text):
        pass


class BalanceJobTests(TestCase):
    def setUp(self):
        self.hosts = [Compute.objects.create(name=f"bj-{n}", hostname=f"192.0.2.5{n}", login="", password="", type=4)
                      for n in range(3)]
        self.vms = [Instance.objects.create(compute=self.hosts[0], name=f"bj-{n}",
                                            uuid=f"00000000-0000-4000-8000-00000000010{n}") for n in range(2)]
        self.admin = get_user_model().objects.create_superuser("bj-admin", "bj@example.com", "pw")
        patcher = patch("instances.jobs.MigrateInstance.validate")  # the hosts are not asked
        patcher.start()
        self.addCleanup(patcher.stop)
        self.moves = [[self.vms[0].pk, self.hosts[0].pk, self.hosts[1].pk],
                      [self.vms[1].pk, self.hosts[0].pk, self.hosts[2].pk]]

    def test_each_vm_migrates_to_its_own_host_and_only_while_running(self):
        params = {"parallel": 2, "moves": self.moves}
        op = Operation.objects.create(kind="host.balance", user=self.admin, username=self.admin.username,
                                      submission_key="key-bal00001", params=params,
                                      intent=Balance().plan(self.admin, params).intent)

        def ends(seconds):
            Operation.objects.filter(kind="instance.migrate").update(state=Operation.SUCCEEDED)

        with patch("computes.jobs.time.sleep", side_effect=ends):
            self.assertEqual(Balance().run(op, Ctx(op)), {})
        children = Operation.objects.filter(kind="instance.migrate", parent=op)
        self.assertEqual(sorted([job.params["instance"], job.params["source"], job.params["target"]] for job in children),
                         self.moves)
        self.assertTrue(all(job.params["running_only"] for job in children))
        self.assertEqual(Balance().progress(op), (2, 2))

    def test_the_computes_page_shows_the_balance_and_the_hosts_pages_not_its_migrations(self):
        balance = jobs.submit("host.balance", self.admin, {"parallel": 1, "moves": self.moves[:1]}, "key-bal00002")
        child = jobs.submit("instance.migrate", self.admin, {"instance": self.vms[0].pk, "target": self.hosts[1].pk},
                            "key-mig00010", parent=balance)
        self.client.force_login(self.admin)

        def shown(key):
            return [job["id"] for job in self.client.get(reverse("operation-resource"), {"key": key}).json()["jobs"]]

        self.assertEqual(shown(claims.bulk_migrate_key()), [str(balance.pk)])
        self.assertEqual(shown(claims.compute_key(self.hosts[0].pk)), [])
        self.assertEqual(shown(claims.instance_key(self.vms[0].uuid)), [str(child.pk)])

    def test_a_move_to_the_vms_own_host_is_refused(self):
        raw = {"parallel": 1, "moves": [[self.vms[0].pk, self.hosts[0].pk, self.hosts[0].pk]]}
        with self.assertRaisesRegex(Exception, "already on its destination"):
            jobs.submit("host.balance", self.admin, raw, "key-bal00003")
