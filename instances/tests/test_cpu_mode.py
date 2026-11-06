"""A new VM's CPU: one of libvirt's modes, or a named model that is that
model, checked by libvirt before the start. That the host offers it is
checked when the job is submitted (test_create_job)."""


from appsettings.models import AppSettings
from appsettings.settings import get_settings
from django.test import TestCase
from instances.tests.create_page import render_create_page
from lxml import html


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
