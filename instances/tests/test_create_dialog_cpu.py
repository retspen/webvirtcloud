"""The new-VM dialog's CPU bars: the page carries each compute's statistics
URL and reads no CPU usage itself; its script fills the bars when the dialog
opens, two computes at a time, and ignores answers of an earlier opening."""

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
function element() {
    const attrs = {};
    return {style: {}, textContent: "", attrs,
            setAttribute: (k, v) => { attrs[k] = String(v); }, removeAttribute: (k) => { delete attrs[k]; }};
}
const cells = URLS.map((url) => {
    const meter = element(), bar = element(), label = element();
    return {dataset: {url}, meter, bar, label,
            querySelector: (sel) => ({".progress": meter, ".progress-bar": bar})[sel] || label};
});
const handlers = {}, requests = [];
const dialog = {addEventListener: (name, fn) => { handlers[name] = fn; }, querySelectorAll: () => cells};
const page = {
    document: {getElementById: () => dialog},
    $: {getJSON: (url) => {
        const r = {url, done: (f) => { r.ok = f; return r; }, fail: (f) => { r.err = f; return r; },
                   always: (f) => { r.end = f; return r; }};
        requests.push(r);
        return r;
    }},
    window: {location: {}},
};
vm.runInNewContext(SCRIPT, vm.createContext(page));
const state = () => cells.map((c) => [c.bar.style.width, c.meter.attrs["aria-valuenow"] || null, c.label.textContent]);
const answer = (i, data) => { const r = requests[i]; data === null ? r.err() : r.ok(data); r.end(); };
const out = {};
handlers["show.bs.modal"]();
out.loading = state();
out.first = requests.map((r) => r.url);
handlers["hide.bs.modal"]();
answer(0, {cpudata: 5});
answer(1, null);
out.hidden = [state(), requests.length];
handlers["show.bs.modal"]();
answer(2, {cpudata: 0});
answer(3, {cpudata: null});
out.filled = state();
handlers["hide.bs.modal"]();
handlers["show.bs.modal"]();
out.reopened = requests.length;
answer(4, {cpudata: 99});
answer(5, {cpudata: 41.6});
answer(6, null);
out.final = state();
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
    def test_the_dialog_fills_the_bars_two_at_a_time(self):
        page = self.page()
        script = next(s for s in html.fromstring(page).xpath("//script[not(@src)]/text()") if "show.bs.modal" in s)
        urls = [reverse("compute_graph", args=[c.id]) for c in self.computes]
        js = RUN.replace("SCRIPT", json.dumps(script)).replace("URLS", json.dumps(urls))
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout)
        self.assertEqual(result["loading"], [["0%", None, "…"]] * 3)
        self.assertEqual(result["first"], urls[:2])
        # answers that come after the dialog closed change nothing and read no more
        self.assertEqual(result["hidden"], [[["0%", None, "…"]] * 3, 2])
        # 0 is a value, no value is a dash
        self.assertEqual(result["filled"], [["0%", "0", "0%"], ["0%", None, "—"], ["0%", None, "…"]])
        # reopened while the third read runs: one more read, two in all
        self.assertEqual(result["reopened"], 6)
        # the earlier opening's answer (99) is ignored; a failed read is a dash
        self.assertEqual(result["final"], [["42%", "42", "42%"], ["0%", None, "—"], ["0%", None, "…"]])
        self.assertEqual(result["all"], urls[:2] + urls + urls)
