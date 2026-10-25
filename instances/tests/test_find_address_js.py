"""The address search dialog's script (static/js/find_address.js) fills its
texts with what the search answered, taken as plain text."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "static" / "js" / "find_address.js"

RUN = """
const vm = require("vm");
const text = () => ({textContent: "", classList: {toggle() {}}});
const handlers = {};
const ids = {
    "find-address": {dataset: DATA, addEventListener() {}},
    "find-address-form": {elements: {q: {value: "192.0.2.10"}}, querySelector: () => ({}),
                          addEventListener: (name, fn) => { handlers[name] = fn; }},
    "find-address-error": text(),
    "find-address-results": {tBodies: [{replaceChildren() {}}], classList: {toggle() {}}},
    "find-address-coverage": text(),
};
const answer = ANSWER;
vm.runInNewContext(SCRIPT, vm.createContext({
    document: {getElementById: (id) => ids[id]}, URLSearchParams, Promise, Date, location: {},
    fetch: () => Promise.resolve({redirected: false, json: () => Promise.resolve(answer)}),
}));
handlers.submit({preventDefault() {}});
setTimeout(() => console.log(JSON.stringify(ids["find-address-coverage"].textContent)), 50);
"""

DATA = {"url": "/find", "failed": "failed", "none": "None found.", "noneMac": "No MAC.", "unregistered": "(unregistered)",
        "conflict": "conflict", "checked": "Checked: %(n)s.", "noAgent": "No agent: %(n)s.",
        "unread": "Unread: %(n)s.", "hostsDown": "Not reached: %(hosts)s.",
        "hostsUnfinished": "Not finished: %(hosts)s.", "readAt": "Read.", "someUnchecked": "Some unchecked."}


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class FindAddressScriptTests(unittest.TestCase):
    def test_host_names_are_put_in_as_they_are(self):
        # String.replace reads $& and $' in a replacement as patterns
        answer = {"matches": [], "read_at": "2026-10-25T10:00:00Z",
                  "coverage": {"checked": 2, "hosts_down": ["c$&1"], "hosts_unfinished": ["d$'2"]}}
        js = (RUN.replace("SCRIPT", json.dumps(SCRIPT.read_text())).replace("DATA", json.dumps(DATA))
              .replace("ANSWER", json.dumps(answer)))
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout),
                         "None found. Checked: 2. Not reached: c$&1. Not finished: d$'2. Read.")
