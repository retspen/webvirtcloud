"""Scripts of the VM create page, rendered on libvirt's test driver and run
in Node against stand-ins."""

import json
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from instances.forms import NewVMForm
from instances.tests.create_page import render_create_page
from lxml import html


# Just enough DOM for the page's scripts: elements reach their parts by
# selector, a row template clones a fresh row, and writing HTML throws (rows
# are built from text and nodes only). A random-MAC request waits in replies.
FAKE_DOM = """
class El {
  constructor(parts = {}) {
    Object.assign(this, {parts, dataset: {}, value: "", name: "", textContent: "", children: [], listeners: {},
                         classes: new Set(), options: [], attrs: {}});
    this.classList = {toggle: (c, on) => on ? this.classes.add(c) : this.classes.delete(c),
                      replace: (a, b) => this.classes.delete(a) && !!this.classes.add(b)};
  }
  set innerHTML(v) { throw new Error("HTML written: " + v); }
  part(sel) { return this.parts[sel]; }
  querySelector(sel) { return this.parts[sel]; }
  addEventListener(event, f) { this.listeners[event] = f; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  append(child) { child.parent = this; this.children.push(child); }
  add(option) { this.options.push(option); }
  remove() { this.parent.children.splice(this.parent.children.indexOf(this), 1); }
}
const row_template = names => ({content: {firstElementChild: {cloneNode: () =>
  new El(Object.fromEntries(names.map(n => [n, new El()])))}}});
const templates = {"disk-row": row_template([".row-label", ".disk-device", ".disk-bus", ".row-item", ".row-remove"]),
                   "network-row": row_template(["input", ".row-label", ".row-item", ".row-remove"])};
const fields = {}, all = {};
const field = sel => fields[sel] ??= new El();
const rows = list => field(list).children;
const document = {getElementById: id => templates[id], querySelector: field, querySelectorAll: sel => all[sel] ?? []};
const replies = [];
const $ = Object.assign(() => ({ready: f => f()}), {getJSON: (url, f) => { replies.push(f); return {}; }});
const Option = function (text, value) { return {text, value}; };
// TomSelect: records its added options and items, and calls the page's
// callbacks as TomSelect does (a silent addItem still calls onItemAdd)
class TomSelect {
  constructor(sel, settings) { this.settings = settings; this.added = []; }
  addOption(o) { this.added.push("option " + o.value); }
  addItem(v) { this.added.push("item " + v); this.settings.onItemAdd(v); }
  removeItem(v) { this.settings.onItemRemove(v); }
  enable() { this.enabled = true; }
  disable() { this.enabled = false; }
}
"""

ROWS = ("make_pickers", "new_row", "add_disk_row", "add_network_row", "row_for", "remove_row", "sync_lists",
        "random_mac", "load_buses")


def functions(page, *names):
    """The page's script functions of these names, in this order."""
    return "".join(re.search(rf"\n    function {name}\(.*?\n    }}\n", page, re.S).group(0) for name in names)


def node(script):
    """Run script in Node; returns what it printed, parsed as JSON."""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class CreatePageScriptTests(TestCase):
    def page(self):
        compute, response = render_create_page(self)
        self.assertEqual(response.status_code, 200)
        return compute, response.content.decode()

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_disk_bus_list_is_asked_for_the_page_architecture_and_machine(self):
        compute, page = self.page()
        out = node(f"const COMPUTE = {compute.id}; let asked; const $ = {{getJSON: url => {{ asked = url; }}}};"
                   + functions(page, "load_buses") + "load_buses({}, 'cdrom'); console.log(JSON.stringify(asked));")
        self.assertEqual(out, reverse("buses", args=[compute.id, "i686", "pc", "cdrom"]))

    def test_the_form_has_one_mac_field(self):
        _, page = self.page()
        form = html.fromstring(page).get_element_by_id("create-vm-form")
        self.assertEqual(form.xpath(".//input[@name='mac']/@id"), ["vm_mac"])

    def test_the_row_templates_hold_what_the_rows_use(self):
        # the test driver reports no disk devices or buses
        with patch("vrtManager.connection.wvmConnect.get_disk_device_types", return_value=["disk", "cdrom"]), \
             patch("vrtManager.connection.wvmConnect.get_disk_bus_types", return_value=["sata", "virtio"]):
            _, page = self.page()
        disk = html.fromstring(page).get_element_by_id("disk-row")
        self.assertEqual(disk.xpath(".//select[contains(@class, 'disk-device')]/option/@value"), ["disk", "cdrom"])
        self.assertEqual(disk.xpath(".//select[contains(@class, 'disk-bus')]/option[@selected]/@value"), ["virtio"])
        network = html.fromstring(page).get_element_by_id("network-row")
        self.assertTrue(network.xpath(".//input[@required]"))
        for row in (disk, network):
            for part in ("row-label", "row-item", "row-remove"):
                self.assertTrue(row.xpath(f".//*[contains(@class, '{part}')]"), part)

    def run_rows(self, test):
        """Run the page's row script against the fake DOM, then test."""
        _, page = self.page()
        return node(FAKE_DOM + "let images_control, networks_control;" + functions(page, *ROWS)
                    + "make_pickers();" + test)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_adding_a_disk_keeps_the_others(self):
        out = self.run_rows("""
images_control.addItem("a");
const a = rows("#img-list")[0];
a.part(".disk-device").value = "cdrom"; a.part(".disk-bus").value = "sata";
images_control.addItem("b");
console.log(JSON.stringify([a.part(".disk-device").value, a.part(".disk-bus").value, field("#images").value,
  rows("#img-list").flatMap(r => [r.part(".disk-device").name, r.part(".disk-bus").name])]));""")
        self.assertEqual(out, ["cdrom", "sata", "a,b", ["device0", "bus0", "device1", "bus1"]])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_removing_a_disk_renumbers_the_rest(self):
        out = self.run_rows("""
images_control.addItem("a"); images_control.addItem("b"); images_control.addItem("c");
images_control.removeItem("b");
const c = rows("#img-list")[1];
console.log(JSON.stringify([field("#images").value, c.part(".disk-device").name, c.part(".disk-bus").name,
  c.part(".row-label").textContent]));""")
        self.assertEqual(out, ["a,c", "device1", "bus1", "hdd1"])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_adding_a_network_keeps_typed_macs(self):
        out = self.run_rows("""
networks_control.addItem("default");
const first = rows("#net-list")[0];
first.part("input").value = "52:54:00:00:00:01"; first.part("input").listeners.input();
networks_control.addItem("isolated");
replies[0]({mac: "52:54:00:aa:aa:aa"}); replies[1]({mac: "52:54:00:bb:bb:bb"});
console.log(JSON.stringify([field("#networks").value, field("#vm_mac").value]));""")
        self.assertEqual(out, ["default,isolated", "52:54:00:00:00:01,52:54:00:bb:bb:bb"])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_hostile_volume_name_is_text(self):
        name = "x'\"><img src=x>"
        out = self.run_rows(f"console.log(JSON.stringify(add_disk_row({json.dumps(name)}).part('.row-item').textContent));")
        self.assertEqual(out, name)

    def test_the_pickers_are_named(self):
        # TomSelect points the label of a select it enhances at its own
        # input, so the select is named by aria-label too
        page = html.fromstring(self.page()[1])
        for select in ("image-control", "network-control"):
            with self.subTest(select=select):
                self.assertTrue(page.xpath(f"//label[@for='{select}']"))
                self.assertTrue(page.get_element_by_id(select).get("aria-label"))

    def test_a_mac_per_nic_fits_the_form(self):
        macs = ",".join(f"52:54:00:00:00:{n:02x}" for n in range(8))
        self.assertEqual(NewVMForm.base_fields["mac"].clean(macs), macs)


class DiskSourceAndPresetScriptTests(TestCase):
    """The disk source choice enables only its own fields; a preset fills the
    sizes, picks a new disk and is announced."""

    HARNESS = FAKE_DOM + """
let images_control = new TomSelect("#image-control", {});
const fieldsets = ["new", "existing", "template"].map(s => Object.assign(new El(), {id: "source-" + s}));
all[".disk-source"] = fieldsets;
const presets = [["small", "2", "2048", "40"], ["large", "4", "8192", "80"]].map(function ([label, vcpu, memory, disk]) {
  const button = new El();
  Object.assign(button.dataset, {label, vcpu, memory, disk});
  button.classes.add("text-body");
  return button;
});
all[".preset"] = presets;
const sources = () => fieldsets.map(f => [f.id, !!f.hidden, !!f.disabled]);
const pressed = () => presets.map(b => [b.attrs["aria-pressed"], [...b.classes].join(" ")]);
"""

    def run_script(self, test):
        _, response = render_create_page(self)
        page = response.content.decode()
        return node(self.HARNESS + functions(page, "show_source", "apply_preset", "clear_presets") + test)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_only_the_chosen_source_is_shown_and_sent(self):
        out = self.run_script("""
show_source("existing"); const existing = [sources(), images_control.enabled];
show_source("template"); const template = [sources(), images_control.enabled];
console.log(JSON.stringify({existing, template}));""")
        self.assertEqual(out["existing"], [[["source-new", True, True], ["source-existing", False, False],
                                            ["source-template", True, True]], True])
        self.assertEqual(out["template"], [[["source-new", True, True], ["source-existing", True, True],
                                            ["source-template", False, False]], False])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_preset_fills_the_sizes_and_picks_a_new_disk(self):
        out = self.run_script("""
show_source("template");
apply_preset(presets[1]);
const applied = {sizes: ["#vm_vcpu", "#vm_memory", "#vm_hdd_size"].map(s => field(s).value),
  radio: field('input[name="disk_source"][value="new"]').checked, sources: sources(), pressed: pressed(),
  status: field("#preset-status").textContent};
clear_presets();
console.log(JSON.stringify({applied, cleared: pressed()}));""")
        applied = out["applied"]
        self.assertEqual(applied["sizes"], ["4", "8192", "80"])
        self.assertTrue(applied["radio"])
        self.assertEqual(applied["sources"][0], ["source-new", False, False])
        self.assertEqual(applied["pressed"], [["false", "text-body"], ["true", "btn-primary"]])
        self.assertEqual(applied["status"], "large: 4 vCPU, 8192 MiB, new 80 GiB disk")
        self.assertEqual(out["cleared"], [["false", "text-body"], ["false", "text-body"]])


class NewFormScriptTests(TestCase):
    """A new form starts with one interface; the template's copy goes into the
    template's pool unless the user picks another."""

    def script(self, test):
        _, response = render_create_page(self)
        page = response.content.decode()
        return node(FAKE_DOM + "let images_control, networks_control;" + functions(page, *ROWS)
                    + functions(page, "add_first_network", "select_value", "template_pool_chosen") + "make_pickers();" + test)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_new_form_starts_on_default_if_the_host_has_it(self):
        for networks, first in ((["isolated", "default"], "default"), (["isolated", "lab"], "isolated"), ([], None)):
            with self.subTest(networks=networks):
                out = self.script(f"networks_control.options = Object.fromEntries({json.dumps(networks)}.map(n => [n, {{}}]));"
                                  "add_first_network(); console.log(JSON.stringify(rows('#net-list').map(r => r.dataset.item)));")
                self.assertEqual(out, [first] if first else [])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_copy_goes_into_the_template_pool(self):
        out = self.script("""
const load_templates = pool => {};
field("#template_storage").options = [{value: "default"}, {value: "templates"}];
template_pool_chosen("templates");
console.log(JSON.stringify(field("#template_storage").value));""")
        self.assertEqual(out, "templates")


class RestoreScriptTests(TestCase):
    """A refused form's lists and template come back, loaded in order, then
    the focus goes to the first error."""

    LISTS = {"pool": "default",
             "disks": [{"volume": "a.qcow2", "device": "cdrom", "bus": "sata"},
                       {"volume": "b.qcow2", "device": "disk", "bus": "virtio"}],
             "networks": [{"name": "default", "mac": "52:54:00:00:00:01"}, {"name": "isolated", "mac": ""}]}

    def run_restore(self, test, lists=LISTS):
        """Run restore_submitted against the fake DOM, with loaders that
        answer when the test calls answer()."""
        _, response = render_create_page(self)
        page = response.content.decode()
        harness = FAKE_DOM + "let images_control, networks_control;" \
            + functions(page, *ROWS[:-1], "select_value", "restore_submitted") + """
templates["submitted-lists"] = {textContent: %s};
$.when = (...loading) => Promise.all(loading);
const log = [], answers = [];
const later = name => { log.push(name); return new Promise(done => answers.push(() => { log.push("loaded " + name); done(); })); };
const load_volumes = pool => later("volumes " + pool);
const load_buses = (bus, device) => later("buses " + device);
const load_templates = pool => later("templates " + pool);
const bootstrap = {Collapse: {getOrCreateInstance: () => ({show: () => log.push("open advanced")})}};
let focused;
const restored = new Promise(done => { focused = done; });
const focusFirstError = () => { log.push("focus"); focused(); };
const settle = () => new Promise(done => setTimeout(done));
const answer = async () => { await settle(); answers.shift()(); await settle(); };
const disks = () => rows("#img-list").map(r => [r.dataset.item, r.part(".disk-device").value, r.part(".disk-bus").value]);
make_pickers();
""" % json.dumps(json.dumps(lists))
        return node(harness + "(async () => {" + test + "})();")

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_lists_are_rebuilt_in_order(self):
        out = self.run_restore("""
restore_submitted();
await answer();
const before = disks();
await answer(); await answer(); await restored;
const typed_before_reply = field("#vm_mac").value;
replies[0]({mac: "52:54:00:00:00:bb"});
console.log(JSON.stringify({log, before, after: disks(), networks: field("#networks").value,
  typed_before_reply, macs: field("#vm_mac").value, random_requests: replies.length}));""")
        self.assertEqual(out["log"], ["volumes default", "loaded volumes default", "buses cdrom", "buses disk",
                                      "loaded buses cdrom", "loaded buses disk", "focus"])
        self.assertEqual(out["before"], [["a.qcow2", "cdrom", ""], ["b.qcow2", "disk", ""]])
        self.assertEqual(out["after"], [["a.qcow2", "cdrom", "sata"], ["b.qcow2", "disk", "virtio"]])
        self.assertEqual(out["networks"], "default,isolated")
        self.assertEqual(out["typed_before_reply"], "52:54:00:00:00:01,")
        self.assertEqual(out["macs"], "52:54:00:00:00:01,52:54:00:00:00:bb")
        self.assertEqual(out["random_requests"], 1)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_value_gone_from_the_lists_is_kept(self):
        out = self.run_restore("""
restore_submitted();
await answer();
const bus = rows("#img-list")[0].part(".disk-bus");
bus.options.push({value: "virtio"});  // the loaded list has no sata
await answer(); await answer(); await restored;
console.log(JSON.stringify({volumes: images_control.added, bus: bus.value,
  options: bus.options.map(o => o.value)}));""")
        self.assertEqual(out["volumes"], ["option a.qcow2", "item a.qcow2", "option b.qcow2", "item b.qcow2"])
        self.assertEqual(out["bus"], "sata")
        self.assertEqual(out["options"], ["virtio", "sata"])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_an_advanced_section_with_an_error_opens_before_the_focus(self):
        out = self.run_restore("""
field("#advanced").parts[".is-invalid"] = new El();
restore_submitted(); await restored;
console.log(JSON.stringify(log));""", lists={"pool": "", "disks": [], "networks": []})
        self.assertEqual(out, ["open advanced", "focus"])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_template_comes_back_after_its_pool_loads(self):
        out = self.run_restore("""
Object.assign(field("#create-vm-form").dataset, {templatePool: "pool-a", template: "base.img"});
restore_submitted();
const pool = field("#template_pool").value;
await answer(); await restored;
console.log(JSON.stringify({log, pool, template: field("#template").value}));""",
                               lists={"pool": "", "disks": [], "networks": []})
        self.assertEqual(out, {"log": ["templates pool-a", "loaded templates pool-a", "focus"],
                               "pool": "pool-a", "template": "base.img"})
