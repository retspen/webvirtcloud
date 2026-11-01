"""Pages poll the server through static/js/poll.js: one request at a time,
none while the page is hidden. Its behaviour is checked with Node."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from django.conf import settings

BASE = Path(settings.BASE_DIR)
POLLING_TEMPLATES = ["instances/templates/instance.html", "computes/templates/overview.html"]


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
        for template in POLLING_TEMPLATES:
            with self.subTest(template=template):
                source = (BASE / template).read_text()
                self.assertNotIn("setInterval", source)
                self.assertIn("pollWhileVisible(", source)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_vm_page_reloads_only_when_the_state_changes(self):
        # "status" is a property of the browser's window: a page variable of
        # that name holds what the browser makes of it (a string, or nothing)
        source = (BASE / "instances/templates/instance.html").read_text()
        script = re.search(r"<script>\s*(backgroundJobRunning = false;.*?)</script>", source, re.S).group(1)
        script = script.replace("{{ instance.status|lower }}", "1").replace(
            "{% url 'instances:status' instance.id %}", "/instances/1/status/"
        )
        js = """
        const vm = require("vm");
        const results = {};
        for (const answer of [1, 5]) {
            let reloads = 0;
            const page = {
                pollWhileVisible: (interval, request, onData) => { onData({status: answer}); return {stop() {}}; },
                $: () => ({submit() {}}),
            };
            page.window = {location: {reload: () => reloads++}};
            Object.defineProperty(page, "status", {get: () => "", set: () => {}});
            vm.runInNewContext(SCRIPT, vm.createContext(page));
            results[answer] = reloads;
        }
        console.log(JSON.stringify(results));
        """.replace("SCRIPT", json.dumps(script))
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {"1": 0, "5": 1})
