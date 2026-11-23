"""The Balance page's script (static/js/balance.js): a ticked or unticked VM
makes the proposal again; the header box ticks or unticks every VM listed
first."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "static" / "js" / "balance.js"

RUN = """
const vm = require("vm");
const boxes = [{name: "vm", id: "moves", checked: true}, {name: "vm", id: "stays", checked: false}];
let handler, submitted = 0;
const form = {elements: boxes, submit: () => { submitted += 1; }};
const other = {elements: [], submit: () => { throw new Error("another form"); }};
vm.runInNewContext(SCRIPT, vm.createContext({document: {
    getElementById: () => form,
    addEventListener: (name, fn) => { handler = fn; },
}}));
const seen = [];
for (const [id, checked, owner] of STEPS) {
    handler({target: {id, checked, form: owner === "other" ? other : form}});
    seen.push(boxes.filter((b) => b.checked).map((b) => b.id));
}
console.log(JSON.stringify({seen, submitted}));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class BalanceScriptTests(unittest.TestCase):
    def run_script(self, steps):
        """{seen: the ticked VMs after each step, submitted: the form's reloads}."""
        code = f"const SCRIPT = {json.dumps(SCRIPT.read_text())};" + RUN.replace("STEPS", json.dumps(steps))
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True, timeout=30)
        return json.loads(out.stdout)

    def test_a_vm_box_makes_the_proposal_again(self):
        self.assertEqual(self.run_script([["balance-7", False]]), {"seen": [["moves"]], "submitted": 1})

    def test_a_change_outside_the_proposal_does_not_reload_it(self):
        self.assertEqual(self.run_script([["balance-parallel", True, "other"]])["submitted"], 0)

    def test_select_all_ticks_or_unticks_every_vm_and_makes_the_proposal_again(self):
        result = self.run_script([["balance-all", True], ["balance-all", False]])
        self.assertEqual(result, {"seen": [["moves", "stays"], []], "submitted": 2})
