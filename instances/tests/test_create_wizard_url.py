"""The create wizard's first page sends the browser to the next page for the
chosen architecture and machine type; the URL is built from placeholders."""

import json
import re
import subprocess
import shutil
import unittest

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase


class CreateWizardUrlTests(TestCase):
    def render_script(self):
        compute = Compute.objects.create(name="cw", hostname="10.0.0.6", login="u", password="p", type=1)
        request = RequestFactory().get("/")
        request.user = get_user_model().objects.create_superuser("cw-admin", "cw@example.com", "pw")
        page = render_to_string("create_instance_w1.html", {"compute": compute}, request=request)
        # the function that builds the URL from arch and machine
        return re.search(r"function create_url\(arch, machine\) \{.*?\n    \}", page, re.S).group(0)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_arch_and_machine_names_land_in_their_segments(self):
        script = self.render_script()
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
        compute = Compute.objects.create(name="cw2", hostname="10.0.0.7", login="u", password="p", type=1)
        request = RequestFactory().get("/")
        request.user = get_user_model().objects.create_superuser("cw2-admin", "cw2@example.com", "pw")
        page = render_to_string("create_instance_w1.html", {"compute": compute, "compute_id": compute.id}, request=request)
        function = re.search(r"function load_machines\(arch\) \{.*?\n    \}", page, re.S).group(0)
        for machines, disabled in (([], True), (["q35"], False)):
            js = ("const next = {disabled: false}, select = {replaceChildren() {}};"
                  "const document = {querySelector: sel => sel === '#next' ? next : select};"
                  "const Option = function () {};"
                  f"const $ = {{getJSON: (url, f) => f({{machines: {machines!r}}})}};"
                  f"{function} load_machines('x86_64'); console.log(next.disabled);")
            out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
            with self.subTest(machines=machines):
                self.assertEqual(out.stdout.strip(), str(disabled).lower(), out.stderr)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_newer_architecture_aborts_the_older_load(self):
        compute = Compute.objects.create(name="cw3", hostname="10.0.0.8", login="u", password="p", type=1)
        request = RequestFactory().get("/")
        request.user = get_user_model().objects.create_superuser("cw3-admin", "cw3@example.com", "pw")
        page = render_to_string("create_instance_w1.html", {"compute": compute, "compute_id": compute.id}, request=request)
        function = re.search(r"function load_machines\(arch\) \{.*?\n    \}", page, re.S).group(0)
        js = ("const next = {}, select = {children: ['pc'], replaceChildren(...items) { this.children = items; }};"
              "const document = {querySelector: sel => sel === '#next' ? next : select};"
              "const Option = function (text) { this.text = text; }; const requests = [];"
              "const $ = {getJSON: (url, fill) => { const r = {fill, abort() { r.aborted = true; }}; requests.push(r); return r; }};"
              f"{function} load_machines('x86_64'); const loading = select.children; load_machines('aarch64');"
              "requests[1].fill({machines: ['virt']});"
              "console.log(JSON.stringify({loading, aborted: requests.map(r => !!r.aborted), filled: select.children.map(o => o.text)}));")
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(json.loads(out.stdout), {"loading": [], "aborted": [True, False], "filled": ["virt"]}, out.stderr)
