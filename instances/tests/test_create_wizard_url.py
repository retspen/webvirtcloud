"""The create wizard's first page sends the browser to the next page for the
chosen architecture and machine type; the URL is built from placeholders."""

import json
import re
import subprocess
import shutil
import unittest

from computes.models import Compute
from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from lxml import html

SCRIPT = (settings.BASE_DIR / "static/js/create_machine.js").read_text()


def function(name):
    """The page script's function of this name."""
    return re.search(rf"\nfunction {name}\(.*?\n}}\n", SCRIPT, re.S).group(0)


class CreateWizardUrlTests(TestCase):
    def render_page(self):
        compute = Compute.objects.create(name="cw", hostname="10.0.0.6", login="u", password="p", type=1)
        request = RequestFactory().get("/")
        request.user = get_user_model().objects.create_superuser("cw-admin", "cw@example.com", "pw")
        return compute, html.fromstring(render_to_string("create_instance_w1.html", {"compute": compute}, request=request))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_arch_and_machine_names_land_in_their_segments(self):
        _, page = self.render_page()
        create_url = page.get_element_by_id("next").get("data-create-url")
        script = ("const document = {querySelector: () => ({dataset: {createUrl: %s}})};" % json.dumps(create_url)
                  + function("create_url"))
        cases = {
            ("x86_64", "q35"): "x86_64/q35/",
            ("ppc64le", "pseries"): "ppc64le/pseries/",  # contains "pc"
            ("aarch64", "virt"): "aarch64/virt/",
        }
        for (arch, machine), tail in cases.items():
            js = "%s console.log(create_url(%r, %r));" % (script, arch, machine)
            out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
            with self.subTest(arch=arch):
                self.assertTrue(out.stdout.strip().endswith(f"/{tail}"), out.stdout + out.stderr)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_next_waits_for_a_machine_type(self):
        load_machines = function("load_machines")
        for machines, disabled in (([], True), (["q35"], False)):
            js = ("const next = {disabled: false}, select = {dataset: {machinesUrl: '/__arch__/'}, replaceChildren() {}};"
                  "const document = {querySelector: sel => sel === '#next' ? next : select};"
                  "const Option = function () {};"
                  f"const $ = {{getJSON: (url, f) => f({{machines: {machines!r}}})}};"
                  f"{load_machines} load_machines('x86_64'); console.log(next.disabled);")
            out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
            with self.subTest(machines=machines):
                self.assertEqual(out.stdout.strip(), str(disabled).lower(), out.stderr)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_newer_architecture_aborts_the_older_load(self):
        load_machines = function("load_machines")
        js = ("const next = {}, select = {dataset: {machinesUrl: '/__arch__/'}, children: ['pc'], replaceChildren(...items) { this.children = items; }};"
              "const document = {querySelector: sel => sel === '#next' ? next : select};"
              "const Option = function (text) { this.text = text; }; const requests = [];"
              "const $ = {getJSON: (url, fill) => { const r = {fill, abort() { r.aborted = true; }}; requests.push(r); return r; }};"
              f"{load_machines} load_machines('x86_64'); const loading = select.children; load_machines('aarch64');"
              "requests[1].fill({machines: ['virt']});"
              "console.log(JSON.stringify({loading, aborted: requests.map(r => !!r.aborted), filled: select.children.map(o => o.text)}));")
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(json.loads(out.stdout), {"loading": [], "aborted": [True, False], "filled": ["virt"]}, out.stderr)
