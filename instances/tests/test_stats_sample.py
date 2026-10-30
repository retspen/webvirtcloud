"""The VM stats: each answer carries a signed usage sample bound to the VM on
its compute; the next poll sends it back so that the rates are averages since
then, without waiting."""

import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase
from django.urls import reverse
from lxml import html
from instances.models import Instance
from vrtManager.instance import USAGE_MAX_WINDOW

# the page script runs after the shared chart helpers
CHARTS_JS = settings.BASE_DIR / "static" / "js" / "charts.js"

SAMPLE = {"key": [7, 4, ["vda"], [["52:54:00:00:00:01", "vnet0"]]], "counters": [1, [[2, 3]], [[4, 5]], 100.0]}


class StatsViewTestCase(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="stats", hostname="192.0.2.1", login="u", password="p", type=1)
        self.other_compute = Compute.objects.create(name="stats2", hostname="192.0.2.2", login="u", password="p", type=1)
        uuid = "5d1b8a3e-0000-4000-8000-000000000001"
        self.vm = Instance.objects.create(compute=self.compute, name="stats-vm", uuid=uuid)
        self.other = Instance.objects.create(compute=self.compute, name="stats-vm2", uuid=uuid.replace("1", "2"))
        self.client.force_login(get_user_model().objects.create_superuser("sv-admin", "sv@example.com", "pw"))
        patcher = patch("instances.models.wvmInstance")
        self.addCleanup(patcher.stop)
        self.proxy = patcher.start().return_value
        self.proxy.mem_usage.return_value = {"used": 1, "total": 2}
        self.proxy.usage.return_value = {
            "cpu": 12.345,
            "disks": [{"dev": "vda", "rd": 2_000_000, "wr": None}],
            "nics": [{"mac": "52:54:00:00:00:01", "rx": 8_000_000, "tx": 0}],
            "window": 9.96,
            "sample": SAMPLE,
        }

    def stats(self, vm=None, **params):
        response = self.client.get(reverse("instances:stats", args=[(vm or self.vm).id]), params)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def previous(self):
        return self.proxy.usage.call_args.args[0]

    def test_rates_in_mb_and_mbit_per_second_and_the_sample_round_trip(self):
        data = self.stats()
        self.assertIsNone(self.previous())
        self.assertEqual((data["cpudata"], data["window"]), (12.3, 10.0))
        self.assertEqual(data["blkdata"], [{"dev": "vda", "data": [2.0, None]}])
        self.assertEqual(data["netdata"], [{"mac": "52:54:00:00:00:01", "data": [8.0, 0.0]}])
        self.stats(sample=data["sample"])
        self.assertEqual(self.previous(), SAMPLE)

    def test_an_altered_old_or_foreign_sample_is_not_used(self):
        token = self.stats()["sample"]
        foreign = self.stats(self.other)["sample"]
        altered = token[:-2] + ("xx" if not token.endswith("xx") else "yy")
        for name, sample in (("altered", altered), ("garbage", "x"), ("other VM", foreign)):
            with self.subTest(name):
                self.stats(sample=sample)
                self.assertIsNone(self.previous())
        with patch("django.core.signing.time.time", return_value=signing.time.time() + USAGE_MAX_WINDOW + 1):
            self.stats(sample=token)
        self.assertIsNone(self.previous())

    def test_a_sample_from_before_a_migration_is_not_used(self):
        token = self.stats()["sample"]
        Instance.objects.filter(pk=self.vm.pk).update(compute=self.other_compute)
        self.stats(sample=token)
        self.assertIsNone(self.previous())

    def test_a_vm_that_is_not_running_gives_no_sample(self):
        self.proxy.usage.return_value = {"cpu": 0, "disks": [], "nics": []}
        data = self.stats()
        self.assertEqual(data["cpudata"], 0)
        self.assertNotIn("sample", data)
        self.assertNotIn("window", data)


# a VM with a disk and a NIC, on libvirt's test driver
DOMAIN = """<domain type='test'><name>stats-script-vm</name><uuid>3c0e2b7a-91d4-4f5e-8a6b-0d2f4e6a8c10</uuid>
<memory unit='MiB'>128</memory><vcpu>1</vcpu><os><type arch='i686'>hvm</type></os>
<devices><disk type='file' device='disk'><source file='/default-pool/stats-script.img'/><target dev='vda' bus='virtio'/></disk>
<interface type='network'><mac address='52:54:00:00:00:31'/><source network='default'/><model type='virtio'/></interface></devices>
</domain>"""


class TestDriverVM:
    def setUp(self):
        self.conn = libvirt.open("test:///default")
        self.addCleanup(self.conn.close)
        # the test host lives on while a libvirt object still refers to it
        pool = self.conn.storagePoolLookupByName("default-pool")
        if "stats-script.img" not in pool.listVolumes():
            pool.createXML("<volume><name>stats-script.img</name><capacity>1048576</capacity></volume>", 0)
        self.domain = self.conn.defineXML(DOMAIN)
        compute = Compute.objects.create(name="ss", hostname="localhost", login="", password="", type=4)
        self.vm = Instance.objects.create(compute=compute, name=self.domain.name(), uuid=self.domain.UUIDString())
        self.client.force_login(get_user_model().objects.create_superuser("ss-admin", "ss@example.com", "pw"))
        for target, value in (
            ("vrtManager.connection.connection_manager.get_connection", self.conn),
            ("vrtManager.connection.wvmConnect.get_machine_types", ["pc"]),
            ("vrtManager.connection.wvmConnect.get_nwfilters", []),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)


class SampleRoundTripTestCase(TestDriverVM, TestCase):
    def test_a_real_sample_is_used_by_the_next_poll(self):
        self.domain.create()
        self.addCleanup(self.domain.destroy)
        url = reverse("instances:stats", args=[self.vm.id])
        with patch("vrtManager.instance.time.sleep") as sleep:
            first = json.loads(self.client.get(url).content)
            sleep.assert_called_once_with(1)
            sleep.reset_mock()
            second = json.loads(self.client.get(url, {"sample": first["sample"]}).content)
        sleep.assert_not_called()
        self.assertEqual([disk["dev"] for disk in second["blkdata"]], ["vda"])
        self.assertIn("sample", second)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class StatsScriptTestCase(TestDriverVM, TestCase):
    """The VM page's script sends each answer's sample with the next poll and
    drops it after a failed one."""

    def page(self):
        response = self.client.get(reverse("instances:instance", args=[self.vm.id]))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_the_next_poll_sends_the_previous_sample(self):
        script = next(s for s in html.fromstring(self.page()).xpath("//script[not(@src)]/text()") if "statsSample" in s)
        js = """
        const vm = require("vm");
        const charts = [], requests = [], handlers = {};
        let poll, fail = false;
        const canvas = {get: () => ({getContext: () => ({})})};
        const $ = () => canvas;
        $.getJSON = (url, params) => {
            requests.push(params);
            return {fail: (callback) => { if (fail) callback(); return {}; }};
        };
        const page = {
            $,
            document: {body: {}, getElementById: () => ({}),
                       querySelector: () => ({addEventListener: (name, handler) => { handlers[name] = handler; }})},
            // Chart.js adds the lists a config leaves out
            getComputedStyle: () => ({getPropertyValue: () => ""}),
            Chart: Object.assign(function (canvas, config) {
                this.data = Object.assign({labels: []}, config.data);
                this.data.datasets.forEach((set) => { set.data = set.data || []; });
                this.options = config.options;
                this.update = () => {};
                charts.push(this);
            }, {defaults: {}}),
            pollWhileVisible: (interval, request, onData, first) => { poll = {interval, first, request, onData}; return {}; },
        };
        const context = vm.createContext(page);
        vm.runInContext(CHARTS, context);
        vm.runInContext(SCRIPT, context);
        handlers["shown.bs.tab"]();
        const answer = (cpu, sample) => ({cpudata: cpu, window: 9.9, sample: sample, timeline: "t",
                                          memdata: {used: 1024, total: 1024},
                                          // vdb was attached after the page loaded
                                          blkdata: [{dev: "vdb", data: [9, 9]}, {dev: "vda", data: [1.5, null]}],
                                          // a NIC is known by its MAC: one added later has no chart
                                          netdata: [{mac: "52:54:00:00:00:99", data: [7, 7]},
                                                    {mac: "52:54:00:00:00:31", data: [2, 3]}]});
        poll.request();
        poll.onData(answer(3, "token-1"));
        poll.request();
        // a VM whose memory could not be read
        poll.onData(Object.assign(answer(4, "token-2"), {memdata: {used: 0, total: 0}}));
        fail = true;
        poll.request();
        fail = false;
        poll.request();
        const label = charts[0].options.plugins.tooltip.callbacks.label({dataset: {label: "Usage"}, formattedValue: "3", dataIndex: 0});
        console.log(JSON.stringify({requests, label, every: [poll.interval, poll.first], cpu: charts[0].data.datasets[0].data,
                                    disk: charts[2].data.datasets[1].data, net: charts[3].data.datasets[0].data,
                                    mem: charts[1].data.datasets[0].data, memMax: charts[1].options.scales.y.max}));
        """.replace("SCRIPT", json.dumps(script)).replace("CHARTS", json.dumps(CHARTS_JS.read_text()))
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout)
        # the first poll at once, then every 5 s
        self.assertEqual(result["every"], [5000, 0])
        # the sample goes with the next poll; a failed poll drops it
        self.assertEqual(result["requests"], [{}, {"sample": "token-1"}, {"sample": "token-2"}, {}])
        # a disk without a chart is skipped, the other charts still update
        self.assertEqual((result["cpu"], result["disk"], result["net"]), ([3, 4], [None, None], [2, 2]))
        # memory that could not be read leaves a gap and keeps the axis
        self.assertEqual((result["mem"], result["memMax"]), ([1, None], 1))
        self.assertTrue(result["label"].endswith(": 3 % (average over 9.9 s)"), result["label"])
