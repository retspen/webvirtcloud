"""The Bulk Migrate page's script (static/js/bulk_migrate.js): another
destination reloads the list; the header box ticks or unticks every VM that
can migrate, "Also migrate the shut-off VMs" only the shut-off ones; a
refused VM stays unticked; a tag chosen ticks the VMs with it. The button counts the ticked VMs. Spread over the
hosts, every change reloads the list."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "static" / "js" / "bulk_migrate.js"

RUN = """
const vm = require("vm");
const boxes = [
    {name: "run", checked: true, disabled: false, shutOff: false, dataset: {tags: "web"}},
    {name: "off", checked: false, disabled: false, shutOff: true, dataset: {tags: "prod web"}},
    {name: "refused", checked: false, disabled: true, shutOff: false, dataset: {tags: "prod"}},
];
const handlers = {};
const box = (id) => ({id, addEventListener: (name, fn) => { handlers[id] = fn; }});
const button = {disabled: false}, counter = {textContent: ""};
let submitted = 0, shownRemoved = 0;
const choose = {
    dataset: SPREAD ? {spread: ""} : {},
    submit: () => { submitted += 1; },
    querySelectorAll: () => [{remove: () => { shownRemoved += 1; }}],
};
const ids = {"bulk-migrate-all": box("bulk-migrate-all"), "bulk-migrate-shut-off": box("bulk-migrate-shut-off"),
             "bulk-migrate-tag": box("bulk-migrate-tag"),
             "bulk-migrate-target": box("bulk-migrate-target"), "bulk-migrate-submit": button,
             "bulk-migrate-count": counter, "bulk-migrate-choose": choose};
const selectors = {
    ".bulk-migrate-vm:not(:disabled)": (b) => !b.disabled,
    ".bulk-migrate-vm[data-shut-off]:not(:disabled)": (b) => b.shutOff && !b.disabled,
    ".bulk-migrate-vm:checked": (b) => b.checked,
};
vm.runInNewContext(SCRIPT, vm.createContext({document: {
    getElementById: (id) => ids[id],
    querySelectorAll: (selector) => boxes.filter(selectors[selector]),
    addEventListener: (name, fn) => { handlers.document = fn; },
}}));
const ticked = () => boxes.filter((b) => b.checked).map((b) => b.name);
const seen = [], counts = [[counter.textContent, button.disabled]];
for (const [id, checked, value] of STEPS) {
    const target = {id, checked, value, form: choose};
    handlers[id]?.({target});
    handlers.document({target});  // the change bubbles to the page
    seen.push(ticked());
    counts.push([counter.textContent, button.disabled]);
}
console.log(JSON.stringify({seen, submitted, counts, shownRemoved}));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class BulkMigrateScriptTests(unittest.TestCase):
    def run_script(self, steps, spread=False):
        """{seen: the ticked VMs after each step, submitted: the list's reloads, counts: the button's
        [count, off] before and after each step, shownRemoved: the spread's VMs dropped from the reload}."""
        code = (f"const SCRIPT = {json.dumps(SCRIPT.read_text())}; const SPREAD = {json.dumps(spread)};"
                + RUN.replace("STEPS", json.dumps(steps)))
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True, timeout=30)
        return json.loads(out.stdout)

    def test_select_all_ticks_every_vm_that_can_migrate(self):
        self.assertEqual(self.run_script([["bulk-migrate-all", True], ["bulk-migrate-all", False]])["seen"],
                         [["run", "off"], []])

    def test_the_shut_off_box_ticks_only_the_shut_off_vms(self):
        result = self.run_script([["bulk-migrate-shut-off", True], ["bulk-migrate-shut-off", False]])
        self.assertEqual(result["seen"], [["run", "off"], ["run"]])

    def test_a_tag_ticks_the_vms_with_it_that_can_migrate_and_only_them(self):
        result = self.run_script([["bulk-migrate-tag", False, "prod"], ["bulk-migrate-tag", False, ""],
                                  ["bulk-migrate-tag", False, "web"]])
        self.assertEqual(result["seen"], [["off"], ["off"], ["run", "off"]])  # "": the ticks stay

    def test_the_button_counts_the_ticked_vms_and_is_off_without_one(self):
        self.assertEqual(self.run_script([["bulk-migrate-all", False], ["bulk-migrate-all", True]])["counts"],
                         [[1, False], [0, True], [2, False]])

    def test_another_destination_reloads_the_list(self):
        result = self.run_script([["bulk-migrate-target", False, "7"]])
        self.assertEqual((result["submitted"], result["shownRemoved"]), (1, 1))

    def test_spread_over_the_hosts_a_change_reloads_the_list(self):
        result = self.run_script([["bulk-migrate-3", False], ["bulk-migrate-parallel", False]], spread=True)
        self.assertEqual(result["submitted"], 1)  # the number at once changes nothing of the list
