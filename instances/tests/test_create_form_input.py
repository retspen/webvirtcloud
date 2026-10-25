"""A refused VM create form comes back bound, with what was entered and the
disk source that was chosen; flavors are presets, not forms."""

import json
import uuid
from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Flavor
from instances.tests.create_page import render_create_page
from lxml import html
from operations import claims, jobs
from operations.models import Operation
from vrtManager import util


def valid(**fields):
    """A create submission NewVMForm accepts."""
    return {"name": "vm1", "firmware": "BIOS", "vcpu": "1", "memory": "512", "networks": "default",
            "cache_mode": "default", "add_cdrom": "None", "add_input": "None", "video": "vga",
            "listener_addr": "0.0.0.0", "submission_key": uuid.uuid4().hex, **fields}


class CreateFormInputTests(TestCase):
    def test_the_page_has_one_unbound_form(self):
        _, response = render_create_page(self)
        self.assertFalse(response.context["vm_form"].is_bound)
        self.assertFalse(response.context["refused"])
        page = html.fromstring(response.content)
        self.assertEqual(len(page.xpath("//form[.//button[@name='create']]")), 1)

    def test_the_refused_form_comes_back_bound(self):
        _, response = render_create_page(self, valid(name="bad name!", vcpu="2"))
        self.assertTrue(response.context["refused"])
        self.assertTrue(response.context["vm_form"].is_bound)
        self.assertIn("name", response.context["vm_form"].errors)

    def test_a_refusal_after_validation_keeps_the_form(self):
        for refusal in (claims.Busy("compute 1"), jobs.SubmissionConflict("already submitted"),
                        util.OperationError("A virtual machine with this name already exists")):
            with self.subTest(refusal=type(refusal).__name__), \
                 patch("instances.views.jobs.submit", side_effect=refusal):
                _, response = render_create_page(self, valid(disk_source="template"))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["disk_source"], "template")
                self.assertTrue(response.context["vm_form"].is_bound)
                self.assertTrue(list(response.context["messages"]))

    def test_a_new_disk_without_a_mac_is_queued(self):
        # as for the other sources, libvirt gives the interface its MAC
        _, response = render_create_page(self, valid(hdd_size="10", storage="default-pool", mac=""))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Operation.objects.get().kind, "instance.create")

    def test_no_form_without_a_storage_pool(self):
        with patch("vrtManager.connection.wvmConnect.get_storages", return_value=[]):
            _, response = render_create_page(self)
        self.assertIsNone(response.context["vm_form"])
        self.assertEqual(html.fromstring(response.content).xpath("//button[@name='create']"), [])
        self.assertTrue(any("storage pools" in str(m) for m in response.context["messages"]))

    def test_a_host_that_cannot_be_read_is_a_message(self):
        import libvirt
        with patch("instances.views.wvmCreate", side_effect=libvirt.libvirtError("unreachable")):
            _, response = render_create_page(self)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("unreachable" in str(m) for m in response.context["messages"]))

    def test_a_valid_post_queues_the_job(self):
        compute, response = render_create_page(self, valid(
            disk_source="new", hdd_size="10", storage="default-pool", mac="52:54:00:00:00:01"))
        self.assertRedirects(response, reverse("instances", args=[compute.id]), fetch_redirect_response=False)
        self.assertEqual(Operation.objects.get().kind, "instance.create")

    def test_the_cloud_init_seed_is_chosen_on_the_form(self):
        _, response = render_create_page(self)
        (box,) = html.fromstring(response.content).xpath("//input[@name='cloud_init']")
        self.assertIsNone(box.get("checked"))
        # the test driver has no CD-ROM bus to pass the job's checks: what the form hands over
        queued = Operation(pk=1, params={"machine": "pc"})
        with patch("instances.views.jobs.submit", return_value=queued) as submit:
            render_create_page(self, valid(disk_source="new", hdd_size="10", storage="default-pool", cloud_init="true"))
        self.assertIs(submit.call_args.args[2]["cloud_init"], True)

    def test_two_disk_sources_are_refused(self):
        # the page sends only the chosen source; a crafted request with two queues nothing
        _, response = render_create_page(self, valid(
            hdd_size="10", template="base.img", storage="default-pool", mac="52:54:00:00:00:01"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("Choose one disk source" in str(m) for m in response.context["messages"]))
        self.assertFalse(Operation.objects.exists())

    def test_impossible_sizes_are_refused_beside_their_fields(self):
        _, response = render_create_page(self, valid(vcpu="0", memory="-1", hdd_size="0", storage="default-pool"))
        self.assertEqual(response.status_code, 200)
        page = html.fromstring(response.content)
        for field in ("vm_vcpu", "vm_memory", "vm_hdd_size"):
            with self.subTest(field=field):
                self.assertIn("greater than or equal to 1", page.get_element_by_id(f"{field}_error").text_content())
        self.assertFalse(Operation.objects.exists())

    def test_a_bad_mac_is_refused_by_the_form(self):
        _, response = render_create_page(self, valid(hdd_size="10", storage="default-pool",
                                                     networks="default,isolated", mac="52:54:00:00:00:01,aa:"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid MAC address", " ".join(response.context["vm_form"].errors.get("mac", [])))
        self.assertFalse(Operation.objects.exists())

    def test_only_the_chosen_disk_source_is_enabled(self):
        for posted, chosen in (("template", "template"), ("existing", "existing"), ("nonsense", "new")):
            with self.subTest(posted=posted):
                _, response = render_create_page(self, valid(name="bad name!", disk_source=posted))
                page = html.fromstring(response.content)
                self.assertEqual(page.xpath("//input[@name='disk_source'][@checked]/@value"), [chosen])
                for source in ("new", "existing", "template"):
                    fieldset = page.get_element_by_id(f"source-{source}")
                    off = source != chosen
                    self.assertEqual((fieldset.get("disabled") is not None, fieldset.get("hidden") is not None),
                                     (off, off), source)


class CreateFormValuesTests(TestCase):
    """The form renders the submitted values and errors."""

    def page(self, **fields):
        _, response = render_create_page(self, valid(**fields))
        self.assertEqual(response.status_code, 200)
        return html.fromstring(response.content)

    def summary(self, page):
        return " ".join(page.xpath("//form[@id='create-vm-form']//*[contains(@class, 'form-errors')]//text()"))

    def test_the_form_keeps_what_was_submitted(self):
        page = self.page(name="bad name!", vcpu="3", memory="2048", cache_mode="writeback")
        self.assertEqual(page.get_element_by_id("vm_name").get("value"), "bad name!")
        self.assertEqual(page.get_element_by_id("vm_vcpu").get("value"), "3")
        self.assertEqual(page.get_element_by_id("vm_memory").get("value"), "2048")
        self.assertEqual(page.xpath("//select[@id='vm_cache_mode']/option[@selected]/@value"), ["writeback"])
        self.assertIsNone(page.get_element_by_id("vm_qemu_ga").get("checked"))  # not submitted: unchecked

    def test_a_new_form_has_its_defaults(self):
        _, response = render_create_page(self)
        page = html.fromstring(response.content)
        self.assertEqual(page.get_element_by_id("vm_vcpu").get("value"), "1")
        self.assertIsNotNone(page.get_element_by_id("vm_qemu_ga").get("checked"))

    def test_a_blank_number_stays_blank(self):
        page = self.page(vcpu="")
        self.assertEqual(page.get_element_by_id("vm_vcpu").get("value"), "")
        self.assertTrue(page.get_element_by_id("vm_vcpu_error").text_content().strip())

    def test_the_name_is_escaped(self):
        page = self.page(name='<b>x</b>"')
        self.assertEqual(page.get_element_by_id("vm_name").get("value"), '<b>x</b>"')
        self.assertEqual(page.xpath("//form[@id='create-vm-form']//b"), [])

    def test_the_error_sits_beside_its_field(self):
        page = self.page(name="bad name!")
        field = page.get_element_by_id("vm_name")
        self.assertIn("is-invalid", field.get("class").split())
        self.assertEqual(field.get("aria-invalid"), "true")
        # described by its help and its error, in one attribute
        self.assertEqual(field.get("aria-describedby").split(), ["vm_name_help", "vm_name_error"])
        self.assertIn("special characters", page.get_element_by_id("vm_name_error").text_content())
        # and in the summary at the top of the form
        self.assertIn("Name: The name of the virtual machine", self.summary(page))

    def test_the_template_source_keeps_its_pool_template_and_storage(self):
        page = self.page(name="bad name!", disk_source="template", template_pool="default-pool",
                         template="base.img", storage="default-pool")
        form = page.get_element_by_id("create-vm-form")
        self.assertEqual((form.get("data-template-pool"), form.get("data-template")), ("default-pool", "base.img"))
        self.assertEqual(page.xpath("//select[@id='template_storage']/option[@selected]/@value"), ["default-pool"])

    def test_an_error_of_a_field_the_form_hides_is_in_its_summary(self):
        # the networks are a hidden input behind a picker
        page = self.page(networks="")
        self.assertIn("Networks: This field is required.", self.summary(page))

    def test_a_firmware_error_without_a_firmware_choice_is_in_the_summary(self):
        # an architecture with no firmware label renders no firmware select
        with patch("vrtManager.connection.wvmConnect.label_for_firmware_path", return_value=None):
            fields = valid()
            del fields["firmware"]
            _, response = render_create_page(self, fields)
        page = html.fromstring(response.content)
        self.assertEqual(page.xpath("//select[@name='firmware']"), [])
        self.assertIn("Firmware: This field is required.", self.summary(page))


class FlavorPresetTests(TestCase):
    """Flavors are presets of the one form; they are managed outside it."""

    def setUp(self):
        self.flavor = Flavor.objects.create(label="wvc-test", memory=512, vcpu=1, disk=10)

    def test_a_flavor_is_a_preset_button(self):
        _, response = render_create_page(self)
        page = html.fromstring(response.content)
        [preset] = page.xpath(f"//button[contains(@class, 'preset')][@data-label='{self.flavor.label}']")
        self.assertEqual((preset.get("data-vcpu"), preset.get("data-memory"), preset.get("data-disk")), ("1", "512", "10"))
        self.assertEqual((preset.get("type"), preset.get("aria-pressed")), ("button", "false"))

    def test_the_flavor_dialog_sits_outside_the_form(self):
        _, response = render_create_page(self)
        page = html.fromstring(response.content)
        self.assertEqual(page.xpath("//form[@id='create-vm-form']//*[@id='flavors-dialog']"), [])
        actions = page.get_element_by_id("flavors-dialog").xpath(".//form/@action")
        self.assertIn(reverse("instances:flavor_delete", args=[self.flavor.id]), actions)
        self.assertEqual(actions[-1], reverse("instances:flavor_create"))


class InPageFlavorTests(TestCase):
    """The create page's flavor forms are sent from the page and get back its
    presets and flavor dialog, so the unfinished VM form stays."""

    def setUp(self):
        self.flavor = Flavor.objects.create(label="wvc-test", memory=512, vcpu=1, disk=10)
        render_create_page(self)  # logs in a superuser

    def post(self, url, data=None):
        response = self.client.post(url, data or {}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["messages"]), [])
        return html.fromstring(response.content)

    def test_an_added_flavor_is_a_preset_and_a_dialog_row(self):
        reply = self.post(reverse("instances:flavor_create"), {"label": "big", "memory": 4096, "vcpu": 4, "disk": 40})
        self.assertEqual(reply.xpath("//*[@id='presets']//button/@data-label")[-2:], ["wvc-test", "big"])
        self.assertEqual(len(reply.xpath("//*[@id='flavors']//li")), Flavor.objects.count())
        self.assertEqual(reply.xpath("//*[@id='flavors']//input[@name='label']/@value"), [])

    def test_a_refused_flavor_shows_its_errors_in_the_dialog(self):
        reply = self.post(reverse("instances:flavor_create"), {"label": "big", "memory": "", "vcpu": 4, "disk": 40})
        self.assertFalse(Flavor.objects.filter(label="big").exists())
        self.assertEqual(reply.xpath("//*[@id='flavors']//input[@name='label']/@value"), ["big"])
        self.assertTrue(reply.xpath("//*[@id='flavors']//input[@name='memory'][contains(@class, 'is-invalid')]"))

    def test_a_deleted_flavor_leaves_the_presets(self):
        reply = self.post(reverse("instances:flavor_delete", args=[self.flavor.id]))
        self.assertNotIn("wvc-test", reply.xpath("//*[@id='presets']//button/@data-label"))
        self.assertNotIn("wvc-test", reply.xpath("//*[@id='flavors']//li//strong/text()"))


class SubmittedListsTests(TestCase):
    """The volumes and networks of a refused form come back with it."""

    def lists(self, response):
        """The volumes and networks the page restores, or None."""
        element = html.fromstring(response.content).get_element_by_id("submitted-lists", None)
        return None if element is None else json.loads(element.text)

    def test_a_refused_form_sends_back_its_lists(self):
        _, response = render_create_page(self, valid(
            name="bad name!", disk_source="existing", **{"storage-control": "default"}, images="a.qcow2,b.qcow2",
            device0="cdrom", bus0="sata", device1="disk", bus1="virtio",
            networks="default,isolated", mac="52:54:00:00:00:01"))
        self.assertEqual(self.lists(response), {
            "pool": "default",
            "disks": [{"volume": "a.qcow2", "device": "cdrom", "bus": "sata"},
                      {"volume": "b.qcow2", "device": "disk", "bus": "virtio"}],
            "networks": [{"name": "default", "mac": "52:54:00:00:00:01"}, {"name": "isolated", "mac": ""}],
        })

    def test_a_hostile_volume_name_round_trips_through_the_lists(self):
        name = "x'\"><img src=x>"
        _, response = render_create_page(self, valid(name="bad name!", disk_source="existing", images=name))
        self.assertEqual(self.lists(response)["disks"][0]["volume"], name)
        self.assertNotIn(b"<img src=x>", response.content)

    def test_only_a_refused_form_sends_lists(self):
        _, response = render_create_page(self)
        self.assertIsNone(self.lists(response))


class XmlRefusalTests(TestCase):
    """A refused XML definition comes back in its open editor, its reason
    beside it."""

    def post(self, xml):
        conn = libvirt.open("test:///default")
        self.addCleanup(conn.close)
        compute, _ = Compute.objects.get_or_create(name="testdrv", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("xml", "xml@example.com", "pw"))
        with patch("vrtManager.connection.connection_manager.get_connection", return_value=conn):
            response = self.client.post(reverse("instances:create_instance_select_type", args=[compute.id]),
                                        {"create_xml": "", "dom_xml": xml})
        self.assertEqual(response.status_code, 200)
        page = html.fromstring(response.content)
        self.assertIn("show", page.get_element_by_id("from-xml").classes)
        self.assertEqual(page.xpath("//*[@id='editor']/text()"), [xml])
        self.assertEqual(page.xpath("//input[@name='dom_xml']/@value"), [xml])
        return page.xpath("//*[@id='from-xml']//*[contains(@class, 'form-errors')]")[0].text_content()

    def test_a_taken_name(self):
        self.assertIn("already exists", self.post("<domain type='test'><name>test</name></domain>"))

    def test_a_definition_without_a_name(self):
        self.assertIn("no name", self.post("<domain type='kvm'><memory>1024</memory></domain>"))

    def test_malformed_xml(self):
        self.assertIn("not well-formed", self.post("<domain type='test'><name>new</name>"))

    def test_a_definition_libvirt_refuses(self):
        self.assertIn("libvirt", self.post("<domain type='nope'><name>new</name><memory>1024</memory></domain>"))
