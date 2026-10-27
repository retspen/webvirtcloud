"""The host CPU graph: usage is taken between the sample of the graph's
previous answer and now, without waiting, when that sample is recent and
unaltered; otherwise over one second as before."""

import json
import shutil
import subprocess
import unittest
from unittest import TestCase as UnitTestCase
from unittest.mock import MagicMock, PropertyMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase
from django.urls import reverse
from libvirt import libvirtError
from lxml import html

from computes.models import Compute
from computes.views import CPU_SAMPLE_MAX_AGE, CPU_SAMPLE_SIGNER
from vrtManager.hostdetails import cpu_percent, wvmHostDetails
from vrtManager.util import ConnectionFailed

# the page script runs after the shared chart helpers
CHARTS_JS = settings.BASE_DIR / "static" / "js" / "charts.js"
TOPOLOGY = {"nodes": 1, "sockets": 1, "cores": 2, "threads": 1, "mhz": 2400, "cpus": 2}


def host(*readings):
    """A wvmHostDetails whose getCPUStats returns readings, (idle, busy) each."""
    h = wvmHostDetails.__new__(wvmHostDetails)
    h.wvm = MagicMock()
    h.wvm.getCPUStats.side_effect = [
        {"kernel": busy // 2, "user": busy - busy // 2, "idle": idle, "iowait": 0, "guest": busy // 3, "utilization": 99}
        for idle, busy in readings
    ]
    return h


class CpuPercentTestCase(UnitTestCase):
    def test_busy_share_between_two_samples(self):
        self.assertEqual(cpu_percent((100, 200), (130, 300)), 70.0)
        self.assertEqual(cpu_percent((0, 0), (1, 3)), 66.7)

    def test_samples_that_do_not_follow_on(self):
        for before, after in (((100, 200), (100, 200)), ((100, 200), (50, 100)), ((100, 200), (200, 250))):
            with self.subTest(before=before, after=after):
                self.assertIsNone(cpu_percent(before, after))


@patch("vrtManager.hostdetails.time")
class CpuUsageTestCase(UnitTestCase):
    def test_since_a_previous_sample_without_waiting(self, clock):
        clock.time.return_value = 105.0
        h = host((130, 70))
        usage = h.get_cpu_usage(previous=(100, 100, 100.0))
        clock.sleep.assert_not_called()
        # total = kernel + user + idle + iowait; guest (inside user) and utilization are left out
        self.assertEqual(usage, {"usage": 70.0, "sample": (130, 200, 105.0), "window": 5.0})

    def test_over_one_second_without_a_sample(self, clock):
        clock.time.side_effect = [10.0, 11.0]
        h = host((100, 100), (110, 190))
        self.assertEqual(h.get_cpu_usage(), {"usage": 90.0, "sample": (110, 300, 11.0), "window": 1.0})
        clock.sleep.assert_called_once_with(1)

    def test_over_one_second_after_the_host_restarted(self, clock):
        clock.time.side_effect = [10.0, 11.0]
        h = host((5, 5), (6, 9))
        usage = h.get_cpu_usage(previous=(1000, 5000, 5.0))
        clock.sleep.assert_called_once_with(1)
        self.assertEqual((usage["usage"], usage["window"]), (80.0, 1.0))


class GraphTestCase(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="graph", hostname="192.0.2.1", login="u", password="p", type=1)
        self.other = Compute.objects.create(name="other", hostname="192.0.2.2", login="u", password="p", type=1)
        admin = get_user_model().objects.create_superuser("graph-admin", "graph@example.com", "pw")
        self.client.force_login(admin)
        for target in ("computes.models.wvmHostDetails", "computes.views.wvmHostDetails"):
            patcher = patch(target)
            self.addCleanup(patcher.stop)
            self.conn = patcher.start().return_value  # the graph reads through wvmHostDetails
        self.conn.get_memory_usage.return_value = {"total": 4, "usage": 1, "percent": 25}
        self.conn.get_cpu_usage.return_value = {"usage": 12.5, "sample": (10, 20, 100.0), "window": 5.04}

    def graph(self, compute=None, **params):
        response = self.client.get(reverse("compute_graph", args=[(compute or self.compute).id]), params)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def previous(self):
        return self.conn.get_cpu_usage.call_args.kwargs["previous"]

    def test_the_answer_carries_the_sample_for_the_next_poll(self):
        data = self.graph()
        self.assertIsNone(self.previous())
        self.assertEqual((data["cpudata"], data["window"], data["memdata"]["percent"]), (12.5, 5.0, 25))
        self.graph(cpu_sample=data["cpu_sample"])
        self.assertEqual(self.previous(), (10, 20, 100.0))

    def test_an_altered_old_or_foreign_sample_is_not_used(self):
        token = self.graph()["cpu_sample"]
        foreign = self.graph(self.other)["cpu_sample"]
        altered = CPU_SAMPLE_SIGNER.sign_object({"compute": self.compute.id, "idle": 0, "total": 1, "time": 0})[:-2] + "xx"
        for name, sample in (("altered", altered), ("garbage", "x"), ("other compute", foreign)):
            with self.subTest(name):
                self.graph(cpu_sample=sample)
                self.assertIsNone(self.previous())
        with patch("django.core.signing.time.time", return_value=signing.time.time() + CPU_SAMPLE_MAX_AGE + 1):
            self.graph(cpu_sample=token)
        self.assertIsNone(self.previous())

    def test_an_unreachable_host_gives_no_cpu_value_and_no_sample(self):
        self.conn.get_cpu_usage.side_effect = libvirtError("unreachable")
        data = self.graph()
        self.assertEqual((data["cpudata"], data["memdata"]["total"]), (None, None))
        self.assertNotIn("cpu_sample", data)

    def test_a_host_that_cannot_be_connected_to_answers_without_values(self):
        down = ConnectionFailed("192.0.2.1 is down")
        with patch("computes.views.wvmHostDetails", side_effect=down), patch(
            "computes.models.wvmHostDetails", side_effect=down
        ):
            self.assertIsNone(self.graph()["cpudata"])
            for url in (reverse("machines", args=[self.compute.id, "x86_64"]),
                        reverse("buses", args=[self.compute.id, "x86_64", "q35", "disk"])):
                self.assertEqual(json.loads(self.client.get(url).content), {})


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class GraphScriptTestCase(TestCase):
    """The overview page's script sends each answer's sample with the next poll."""

    def test_the_next_poll_sends_the_previous_sample(self):
        self.client.force_login(get_user_model().objects.create_superuser("gs-admin", "gs@example.com", "pw"))
        compute = Compute.objects.create(name="gs", hostname="192.0.2.1", login="u", password="p", type=1)
        with patch("computes.views.wvmHostDetails") as details, patch.object(
            Compute, "status", new_callable=PropertyMock, return_value=True
        ), patch.object(Compute, "capacity", new=None), patch("computes.views.host_pools", return_value=None):
            details.return_value.get_node_info.return_value = ("h", "x86_64", 1024, 2, "cpu", "qemu+tcp://h/system")
            details.return_value.get_cpu_topology.return_value = TOPOLOGY
            page = self.client.get(reverse("overview", args=[compute.id])).content.decode()
        script = next(s for s in html.fromstring(page).xpath("//script[not(@src)]/text()") if "pollWhileVisible(" in s)
        js = """
        const vm = require("vm");
        const charts = [], requests = [];
        const element = (dataset) => ({dataset, textContent: "", classList: {add: () => {}, remove: () => {}}});
        const elements = {graph_state: element({updated: "Updated at %(time)s.", stale: "Not updated since %(time)s."}),
                          cpu_now: element({}), mem_now: element({})};
        let poll;
        const page = {
            document: {body: {}, getElementById: (id) => elements[id] || {}},
            // Chart.js adds the lists a config leaves out
            getComputedStyle: () => ({getPropertyValue: () => ""}),
            Chart: Object.assign(function (canvas, config) {
                this.data = Object.assign({labels: []}, config.data);
                this.data.datasets.forEach((set) => { set.data = set.data || []; });
                this.options = config.options;
                this.update = () => {};
                charts.push(this);
            }, {defaults: {}}),
            $: {getJSON: (url, params) => { requests.push(params); return {fail() { return this; }}; }},
            pollWhileVisible: (interval, request, onData) => { poll = {request, onData}; },
        };
        const context = vm.createContext(page);
        vm.runInContext(CHARTS, context);
        vm.runInContext(SCRIPT, context);
        const answer = (cpu, sample) => ({cpudata: cpu, window: 5.1, cpu_sample: sample, timeline: "t",
                                          memdata: {total: 2 * 1073741824, usage: 1073741824}});
        poll.request();
        poll.onData(answer(3, "token-1"));
        const shown = [elements.cpu_now.textContent, elements.mem_now.textContent, elements.graph_state.textContent];
        poll.request();
        poll.onData({cpudata: null, memdata: {total: null, usage: null}, timeline: "t"});
        poll.request();
        const label = charts[0].options.plugins.tooltip.callbacks.label({dataset: {label: "Usage"}, formattedValue: "3", dataIndex: 0});
        console.log(JSON.stringify({requests, label, shown, state: elements.graph_state.textContent,
                                    cpu: charts[0].data.datasets[0].data,
                                    mem: charts[1].data.datasets[0].data, memMax: charts[1].options.scales.y.max}));
        """.replace("SCRIPT", json.dumps(script)).replace("CHARTS", json.dumps(CHARTS_JS.read_text()))
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout)
        self.assertEqual(result["requests"], [{}, {"cpu_sample": "token-1"}, {}])
        self.assertEqual(result["cpu"], [3, None])
        # a host that could not be read leaves a gap and keeps the memory axis
        self.assertEqual((result["mem"], result["memMax"]), ([1, None], 2))
        # the readings in words, and since when they are not updated
        self.assertEqual(result["shown"], ["3 %", "1 / 2 GB", "Updated at t."])
        self.assertEqual(result["state"], "Not updated since t.")
        self.assertTrue(result["label"].endswith(": 3 % (average over 5.1 s)"), result["label"])
