"""A new VM's CPU: one of libvirt's modes, or a named model that is that
model, checked by libvirt before the start. That the host offers it is
checked when the job is submitted (test_create_job)."""

from unittest.mock import MagicMock, patch

from appsettings.models import AppSettings
from appsettings.settings import get_settings
from django.test import SimpleTestCase, TestCase
from instances.tests.create_page import render_create_page
from lxml import etree, html
from vrtManager.create import wvmCreate

DOM_CAPS = {"domain": "kvm", "os_support": "no", "cpu_modes": ["host-passthrough", "maximum", "host-model", "custom"],
            "cpu_custom_models": ["Skylake-Server-noTSX-IBRS", "SandyBridge-IBRS"]}


def defined_cpu(vcpu_mode):
    conn = wvmCreate.__new__(wvmCreate)
    conn.wvm = MagicMock()
    with patch.object(wvmCreate, "get_capabilities", return_value={"features": []}), \
            patch.object(wvmCreate, "get_dom_capabilities", return_value=DOM_CAPS):
        conn.create_instance(name="vm-1", memory=512, vcpu=1, vcpu_mode=vcpu_mode,
                             uuid="00000000-0000-4000-8000-0000000000c1", arch="x86_64", machine="q35",
                             firmware={}, volumes=[], networks="", nwfilter="", virtio=True, listener_addr="0.0.0.0",
                             add_cdrom="None", add_input="None")
    return etree.fromstring(conn.wvm.defineXML.call_args.args[0]).find("cpu")


class CpuModeTests(SimpleTestCase):
    def test_a_mode_is_written_as_the_mode(self):
        for mode in ("host-model", "host-passthrough", "maximum"):
            with self.subTest(mode=mode):
                cpu = defined_cpu(mode)
                self.assertEqual((dict(cpu.attrib), len(cpu)), ({"mode": mode}, 0))

    def test_a_named_model_is_that_model_checked_by_libvirt(self):
        # a name longer than 20 characters too
        cpu = defined_cpu("Skylake-Server-noTSX-IBRS")
        self.assertEqual(dict(cpu.attrib), {"mode": "custom", "match": "exact"})  # no check='none'
        self.assertEqual((cpu.findtext("model"), cpu.find("model").get("fallback")), ("Skylake-Server-noTSX-IBRS", "forbid"))


class CpuModeSelectTests(TestCase):
    def selected(self):
        _, response = render_create_page(self)
        return html.fromstring(response.content).xpath("//select[@id='vm_vcpu_mode']/option[@selected]/@value")

    def test_the_default_mode_is_chosen_when_the_host_offers_it_else_one_is_asked_for(self):
        get_settings()
        self.assertEqual(self.selected(), ["host-model"])
        # not swapped for another mode silently: the browser would take the first one
        AppSettings.objects.filter(key="INSTANCE_CPU_DEFAULT_MODE").update(value="maximum")
        self.assertEqual(self.selected(), [""])
