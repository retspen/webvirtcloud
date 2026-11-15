"""The Bulk Migrate page's script (static/js/bulk_migrate.js): another
destination reloads the list; the header box ticks or unticks every VM that
can migrate, "Also migrate the shut-off VMs" only the shut-off ones; a
refused VM stays unticked."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "static" / "js" / "bulk_migrate.js"

RUN = """
const vm = require("vm");
const boxes = [
    {name: "run", checked: true, disabled: false, shutOff: false},
    {name: "off", checked: false, disabled: false, shutOff: true},
    {name: "refused", checked: false, disabled: true, shutOff: false},
];
const handlers = {};
const box = (id) => ({addEventListener: (name, fn) => { handlers[id] = fn; }});
const ids = {"bulk-migrate-all": box("all"), "bulk-migrate-shut-off": box("shut-off"), "bulk-migrate-target": box("target")};
let submitted = 0;
const selectors = {
    "input[name=instance]:not(:disabled)": (b) => !b.disabled,
    "input[data-shut-off]:not(:disabled)": (b) => b.shutOff && !b.disabled,
};
vm.runInNewContext(SCRIPT, vm.createContext({document: {
    getElementById: (id) => ids[id],
    querySelectorAll: (selector) => boxes.filter(selectors[selector]),
}}));
const ticked = () => boxes.filter((b) => b.checked).map((b) => b.name);
const seen = [];
for (const [id, checked] of STEPS) {
    handlers[id]({target: {checked, form: {submit: () => { submitted += 1; }}}});
    seen.push(ticked());
}
console.log(JSON.stringify({seen, submitted}));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class BulkMigrateScriptTests(unittest.TestCase):
    def run_script(self, steps):
        """{seen: the ticked VMs after each step, submitted: the destination form's reloads}."""
        code = f"const SCRIPT = {json.dumps(SCRIPT.read_text())};" + RUN.replace("STEPS", json.dumps(steps))
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True, timeout=30)
        return json.loads(out.stdout)

    def test_select_all_ticks_every_vm_that_can_migrate(self):
        self.assertEqual(self.run_script([["all", True], ["all", False]])["seen"], [["run", "off"], []])

    def test_the_shut_off_box_ticks_only_the_shut_off_vms(self):
        self.assertEqual(self.run_script([["shut-off", True], ["shut-off", False]])["seen"], [["run", "off"], ["run"]])

    def test_another_destination_reloads_the_list(self):
        self.assertEqual(self.run_script([["target", False]])["submitted"], 1)
