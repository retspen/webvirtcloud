"""The host CPU graph: usage is taken between the sample of the graph's
previous answer and now, without waiting, when that sample is recent and
unaltered; otherwise over one second as before."""

from datetime import datetime, timezone as dt_timezone
import json
import shutil
import subprocess
import unittest
from unittest.mock import PropertyMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings
from django.urls import reverse
from libvirt import libvirtError
from lxml import html

from computes.models import Compute
from computes.views import CPU_SAMPLE_MAX_AGE, CPU_SAMPLE_SIGNER
from vrtManager.util import ConnectionFailed

# the page script runs after the shared chart helpers
CHARTS_JS = settings.BASE_DIR / "static" / "js" / "charts.js"
TOPOLOGY = {"nodes": 1, "sockets": 1, "cores": 2, "threads": 1, "mhz": 2400, "cpus": 2}


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

    @override_settings(TIME_ZONE="Europe/Istanbul")
    def test_the_time_of_a_point_is_the_panels(self):
        with patch("django.utils.timezone.now", return_value=datetime(2026, 11, 10, 9, 0, tzinfo=dt_timezone.utc)):
            self.assertEqual(self.graph()["timeline"], "12:00:00")
            self.conn.get_cpu_usage.side_effect = libvirtError("unreachable")  # its error answer too
            self.assertEqual(self.graph()["timeline"], "12:00:00")

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

    def test_a_host_that_cannot_be_connected_to_answers_without_values_or_with_its_error(self):
        down = ConnectionFailed("192.0.2.1 is down")
        with patch("computes.views.wvmHostDetails", side_effect=down), patch(
            "computes.models.wvmHostDetails", side_effect=down
        ):
            self.assertIsNone(self.graph()["cpudata"])
            for url in (reverse("machines", args=[self.compute.id, "x86_64"]),
                        reverse("buses", args=[self.compute.id, "x86_64", "q35", "disk"])):
                # a list the new VM form waits for: the error, not an empty answer
                response = self.client.get(url)
                self.assertEqual((response.status_code, json.loads(response.content)), (400, {"error": "192.0.2.1 is down"}))


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
        doc = html.fromstring(page)
        self.assertIn("/static/js/host_graphs.js", doc.xpath("//script/@src"))
        (state,) = doc.xpath("//span[@id='graph_state']")
        dataset = {"url": state.get("data-url"), "averageOver": state.get("data-average-over"),
                   "updated": "Updated at %(time)s.", "stale": "Not updated since %(time)s."}
        script = (settings.BASE_DIR / "static/js/host_graphs.js").read_text()
        js = """
        const vm = require("vm");
        const charts = [], requests = [], timeouts = [];
        const element = (dataset) => ({dataset, textContent: "", classList: {add: () => {}, remove: () => {}}});
        const elements = {graph_state: element(DATASET),
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
            $: {ajax: (options) => { requests.push(options.data); timeouts.push(options.timeout); return {fail() { return this; }}; }},
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
        console.log(JSON.stringify({requests, timeouts, label, shown, state: elements.graph_state.textContent,
                                    cpu: charts[0].data.datasets[0].data.map((point) => point.y),
                                    mem: charts[1].data.datasets[0].data.map((point) => point.y), memMax: charts[1].options.scales.y.max}));
        """.replace("SCRIPT", json.dumps(script)).replace("CHARTS", json.dumps(CHARTS_JS.read_text())).replace(
            "DATASET", json.dumps(dataset))
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout)
        self.assertEqual(result["requests"], [{}, {"cpu_sample": "token-1"}, {}])
        # a reading the host keeps waiting ends: the charts then say they are not updated
        self.assertEqual(result["timeouts"], [30000] * 3)
        self.assertEqual(result["cpu"], [3, None])
        # a host that could not be read leaves a gap and keeps the memory axis
        self.assertEqual((result["mem"], result["memMax"]), ([1, None], 2))
        # the readings in words, and since when they are not updated
        self.assertEqual(result["shown"], ["3 %", "1 / 2 GiB", "Updated at t."])
        self.assertEqual(result["state"], "Not updated since t.")
        self.assertTrue(result["label"].endswith(": 3 % (average over 5.1 s)"), result["label"])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ChartAxisTestCase(unittest.TestCase):
    """A reading stands at the time it came, labelled with the panel's time:
    one that took 20 s stands four times as far as one of 5 s."""

    def test_readings_are_spaced_by_their_time(self):
        js = """
        const vm = require("vm");
        let chart;
        const page = {
            document: {body: {}},
            getComputedStyle: () => ({getPropertyValue: () => ""}),
            Chart: Object.assign(function (canvas, config) {
                this.data = config.data; this.options = config.options; this.update = () => {}; chart = this;
            }, {defaults: {}}),
        };
        const context = vm.createContext(page);
        vm.runInContext(CHARTS, context);
        vm.runInContext("var c = lineChart({}, '%', ['Usage']);"
            + " addPoint(c, '12:00:00', [1], 100); addPoint(c, '12:00:05', [2], 105); addPoint(c, '12:00:25', [null], 125);",
            context);
        // 20 px a second: each reading 100 px from the next or more
        const axis = {chart, getPixelForValue: (value) => value * 20};
        chart.options.scales.x.afterBuildTicks(axis);
        const label = (a) => a.ticks.map((tick, i) => chart.options.scales.x.ticks.callback.call(a, tick.value, i, a.ticks));
        const labels = label(axis);
        // 4 px a second: a 5 s step (20 px) leaves no room for its label, a 20 s one (80 px) does
        const packed = {chart, getPixelForValue: (value) => value * 4};
        chart.options.scales.x.afterBuildTicks(packed);
        const packedLabels = label(packed);
        const title = chart.options.plugins.tooltip.callbacks.title([{chart, parsed: {x: 105}}]);
        console.log(JSON.stringify({points: chart.data.datasets[0].data, type: chart.options.scales.x.type, labels, packedLabels,
                                    title}));
        """.replace("CHARTS", json.dumps(CHARTS_JS.read_text()))
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout)
        self.assertEqual(result["type"], "linear")
        self.assertEqual(result["points"], [{"x": 100, "y": 1}, {"x": 105, "y": 2}, {"x": 125, "y": None}])
        self.assertEqual(result["labels"], ["12:00:00", "12:00:05", "12:00:25"])
        self.assertEqual(result["packedLabels"], ["", "12:00:05", "12:00:25"])
        self.assertEqual(result["title"], "12:00:05")
