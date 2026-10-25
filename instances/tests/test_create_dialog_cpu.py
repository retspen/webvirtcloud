"""The new-VM dialog's CPU bars and capacity lines: the page carries each
compute's URLs and reads neither itself; its script fills them when the
dialog opens, two reads at a time, and ignores answers of an earlier
opening."""

import json
import shutil
import subprocess
import unittest
from unittest.mock import PropertyMock, patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from lxml import html

RUN = """
const vm = require("vm");
function element(cls) {
    const attrs = {};
    return {style: {}, textContent: "", attrs, classList: {contains: (c) => c === cls},
            setAttribute: (k, v) => { attrs[k] = String(v); }, removeAttribute: (k) => { delete attrs[k]; }};
}
const cells = CPU_URLS.map((url) => {
    const cell = element("cpu-usage"), meter = element(), bar = element(), label = element();
    cell.dataset = {url};
    cell.querySelector = (sel) => ({".progress": meter, ".progress-bar": bar})[sel] || label;
    Object.assign(cell, {meter, bar, label});
    return cell;
});
const lines = LINE_URLS.map((url) => Object.assign(element("compute-capacity"), {dataset: {url}}));
const handlers = {}, requests = [];
const dialog = {addEventListener: (name, fn) => { handlers[name] = fn; },
                querySelectorAll: (sel) => sel === ".cpu-usage" ? cells : cells.flatMap((c, i) => [c, lines[i]])};
const page = {
    document: {getElementById: () => dialog},
    $: {get: (url) => {
        const r = {url, done: (f) => { r.ok = f; return r; }, fail: (f) => { r.err = f; return r; },
                   always: (f) => { r.end = f; return r; }};
        requests.push(r);
        return r;
    }},
    window: {location: {}},
};
vm.runInNewContext(SCRIPT, vm.createContext(page));
const state = () => [cells.map((c) => [c.bar.style.width, c.meter.attrs["aria-valuenow"] || null, c.label.textContent]),
                     lines.map((l) => l.textContent)];
const answer = (i, data) => { const r = requests[i]; data === null ? r.err() : r.ok(data); r.end(); };
const out = {};
handlers["show.bs.modal"]();
out.loading = state();
handlers["hide.bs.modal"]();
answer(0, {cpudata: 5});
answer(1, "stale");
out.hidden = [state(), requests.length];
handlers["show.bs.modal"]();
answer(2, {cpudata: 41.6});
answer(3, "\\nGiven 1.\\n");
answer(4, null);
answer(5, null);
out.filled = state();
out.all = requests.map((r) => r.url);
console.log(JSON.stringify(out));
"""


class CreateDialogCpuTestCase(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("cd-admin", "cd@example.com", "pw"))
        self.computes = [
            Compute.objects.create(name=f"cd{i}", hostname=f"192.0.2.{i}", login="u", password="p", type=1)
            for i in (1, 2, 3)
        ]
        patches = [
            patch.object(Compute, name, new_callable=PropertyMock, return_value=value)
            for name, value in (("status", True), ("cpu_count", 1), ("ram_size", 1024), ("ram_usage", 0))
        ]
        patches += [patch("instances.views.utils.refr"), patch("computes.models.wvmHostDetails")]
        for p in patches:
            self.details = p.start()  # the last one: the host connection
            self.addCleanup(p.stop)

    def page(self):
        response = self.client.get(reverse("instances:index"))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_the_page_carries_the_statistics_urls_and_reads_no_cpu_usage(self):
        page = self.page()
        urls = html.fromstring(page).xpath("//*[contains(@class, 'cpu-usage ')]/@data-url")
        self.assertEqual(urls, [reverse("compute_graph", args=[c.id]) for c in self.computes])
        self.details.return_value.get_cpu_usage.assert_not_called()

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_dialog_reads_host_by_host_two_at_a_time(self):
        page = self.page()
        script = next(s for s in html.fromstring(page).xpath("//script[not(@src)]/text()") if "show.bs.modal" in s)
        cpu = [reverse("compute_graph", args=[c.id]) for c in self.computes]
        line = [reverse("compute_capacity", args=[c.id]) for c in self.computes]
        js = RUN.replace("SCRIPT", json.dumps(script)).replace("CPU_URLS", json.dumps(cpu)).replace("LINE_URLS", json.dumps(line))
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout)
        waiting = [[["0%", None, "…"]] * 3, ["", "", ""]]
        self.assertEqual(result["loading"], waiting)
        # answers that come after the dialog closed change nothing and read no more
        self.assertEqual(result["hidden"], [waiting, 2])
        # a failed CPU read is a dash, a failed line stays empty
        self.assertEqual(result["filled"], [[["42%", "42", "42%"], ["0%", None, "—"], ["0%", None, "…"]],
                                            ["Given 1.", "", ""]])
        # the CPU and the line of one host, then the next host; two at a time
        self.assertEqual(result["all"], [cpu[0], line[0], cpu[0], line[0], cpu[1], line[1], cpu[2], line[2]])

    def test_each_host_carries_its_capacity_line_url(self):
        urls = html.fromstring(self.page()).xpath("//*[@id='AddInstance']//*[contains(@class, 'compute-capacity')]/@data-url")
        self.assertEqual(urls, [reverse("compute_capacity", args=[c.id]) for c in self.computes])


class CreateDialogHostsTestCase(TestCase):
    """The dialog lists the reachable computes; without one it says so."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("cd-admin", "cd@example.com", "pw"))
        for i in (1, 2):
            Compute.objects.create(name=f"cd{i}", hostname=f"192.0.2.{i}", login="u", password="p", type=1)
        for name, value in (("cpu_count", 1), ("ram_size", 1024), ("ram_usage", 0)):
            p = patch.object(Compute, name, new_callable=PropertyMock, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        p = patch("instances.views.utils.refr")
        p.start()
        self.addCleanup(p.stop)

    def dialog(self, reachable):
        with patch.object(Compute, "status", property(lambda compute: compute.name in reachable)):
            response = self.client.get(reverse("instances:index"))
        return html.fromstring(response.content).get_element_by_id("AddInstance")

    def test_only_reachable_computes_are_listed(self):
        dialog = self.dialog({"cd2"})
        self.assertEqual([e.text for e in dialog.xpath(".//a/div/div[1]")], ["cd2"])
        self.assertNotIn("No compute is reachable.", dialog.text_content())

    def test_no_reachable_compute_is_said(self):
        dialog = self.dialog(set())
        self.assertEqual(dialog.xpath(".//a"), [])
        self.assertIn("No compute is reachable.", dialog.text_content())
