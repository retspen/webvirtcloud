"""Pages poll the server through static/js/poll.js: one request at a time,
none while the page is hidden. Its behaviour is checked with Node."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from django.conf import settings

BASE = Path(settings.BASE_DIR)
POLLING_SOURCES = ["static/js/instance_status.js", "static/js/instance_stats.js", "static/js/host_graphs.js"]


class PollTestCase(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_poll_js(self):
        result = subprocess.run(
            ["node", str(BASE / "webvirtcloud/tests/js/poll.test.js"), str(BASE / "static/js/poll.js")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_vm_states_js(self):
        result = subprocess.run(
            ["node", str(BASE / "webvirtcloud/tests/js/vm_states.test.js"), str(BASE / "static/js/poll.js"),
             str(BASE / "static/js/vm_states.js")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pages_poll_through_poll_js(self):
        for path in POLLING_SOURCES:
            with self.subTest(path=path):
                source = (BASE / path).read_text()
                self.assertNotIn("setInterval", source)
                self.assertIn("pollWhileVisible(", source)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_vm_page_reloads_only_when_the_state_changes_and_it_is_not_in_use(self):
        # "status" is a property of the browser's window: a page variable of
        # that name holds what the browser makes of it (a string, or nothing)
        script = (BASE / "static/js/instance_status.js").read_text()
        js = """
        const vm = require("vm");
        const results = {};
        for (const [answer, inUse] of [[1, false], [5, false], [5, true]]) {
            let reloads = 0;
            const page = {
                pollWhileVisible: (interval, request, onData) => { onData({status: answer}); return {stop() {}}; },
                pageInUse: () => inUse,
                $: () => ({submit() {}}),
                document: {getElementById: () => ({dataset: {status: "1", statusUrl: "/instances/1/status/"}})},
            };
            page.window = {location: {reload: () => reloads++}};
            Object.defineProperty(page, "status", {get: () => "", set: () => {}});
            vm.runInNewContext(SCRIPT, vm.createContext(page));
            results[answer + (inUse ? " in use" : "")] = reloads;
        }
        console.log(JSON.stringify(results));
        """.replace("SCRIPT", json.dumps(script))
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {"1": 0, "5": 1, "5 in use": 0})
