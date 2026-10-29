"""
The VM page renders a control only for users the backend lets use it:
power to superusers and owners; the console, virt-viewer file and VDI URL to
superusers and owners (can_open_console); root password, SSH key, resize and
options to superusers and owners with is_change; per-vCPU hotplug, video
model and guest agent to superusers; clone with clone_instances on a template
or with is_change; snapshots with snapshot_instances and is_change, on a
template only for staff. is_staff and the global view_instances permission
alone are read-only.
"""
import shutil
import subprocess
import unittest
from unittest.mock import PropertyMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from lxml import html as lxml_html

from accounts.models import UserInstance
from appsettings.models import AppSettings
from computes.models import Compute
from instances.models import Instance
from operations.models import Operation

CONSOLE = {"console", "vv file", "vdi"}
POWER = {"power"}
CHANGE = {"root password", "ssh key", "resize", "options"}
SUPERUSER_ONLY = {"vcpu hotplug", "video model", "guest agent"}


class PageControls:
    def setUp(self):
        AppSettings.objects.filter(
            key__in=["SHOW_ACCESS_ROOT_PASSWORD", "SHOW_ACCESS_SSH_KEYS"]
        ).update(value="True")
        self.compute = Compute.objects.create(
            name="ctl-compute", hostname="127.0.0.1:1", login="root", password="", type=1
        )
        self.instance = Instance.objects.create(
            compute=self.compute, name="ctl-vm", uuid="dddddddd-eeee-ffff-0000-111111111111"
        )

    def user(self, name, staff=False, perms=(), owner=None):
        user = get_user_model().objects.create_user(name, password="x", is_staff=staff)
        for codename in perms:
            user.user_permissions.add(Permission.objects.get(codename=codename))
        if owner is not None:
            UserInstance.objects.create(instance=self.instance, user=user, **owner)
        return user

    def controls(self, user, status=1):
        self.client.force_login(user)
        with patch("instances.models.wvmInstance") as mock_wvm, patch.object(
            Compute, "status", new_callable=PropertyMock, return_value=True
        ):
            proxy = mock_wvm.return_value
            proxy.get_memory.return_value = 1024
            proxy.get_cur_memory.return_value = 1024
            proxy.get_max_memory.return_value = 4096
            proxy.get_vcpu.return_value = 2
            proxy.get_cur_vcpu.return_value = 1
            proxy.get_max_cpus.return_value = [1, 2, 3, 4]
            # a running VM with hotpluggable vCPUs shows the per-vCPU buttons
            proxy.get_vcpus.return_value = {
                0: {"enabled": "yes", "hotpluggable": "no"},
                1: {"enabled": "no", "hotpluggable": "yes"},
            }
            for getter in ("get_networks", "get_ifaces", "get_storages", "get_disk_devices",
                           "get_media_devices", "get_net_devices", "get_snapshot",
                           "get_snapshot_jobs"):
                getattr(proxy, getter).return_value = []
            proxy.get_hostdevs.return_value = ([], [], [])
            proxy.get_console_type.return_value = "vnc"
            proxy.get_status.return_value = status
            response = self.client.get(reverse("instances:instance", args=[self.instance.id]))
        self.assertEqual(response.status_code, 200)
        self.last_page = response.content.decode()
        doc = lxml_html.fromstring(response.content)
        pk = self.instance.id

        def form(name):
            return bool(doc.xpath("//form[@action=$a]", a=reverse(f"instances:{name}", args=[pk])))

        found = {
            "console": bool(doc.xpath("//button[@id='console_button']")),
            "vv file": bool(doc.xpath("//a[@href=$a]", a=reverse("instances:getvvfile", args=[pk]))),
            "vdi": bool(doc.xpath("//*[@id='vdiconsole']")),
            "power": form("poweroff") or form("poweron"),
            "root password": form("rootpasswd"),
            "ssh key": form("add_public_key"),
            # a running VM with hotplug shows per-vCPU buttons instead of the CPU form
            "resize": form("resize_memory"),
            "options": form("change_options"),
            "console settings": form("update_console"),
            # host pages (superuser-only views)
            "host links": bool(doc.xpath("//a[@href=$a]", a=reverse("overview", args=[self.compute.id]))),
            # a link to the destroy confirmation page
            "destroy": bool(doc.xpath("//a[@href=$a]", a=reverse("instances:destroy", args=[pk]))),
            "vcpu hotplug": form("set_vcpu"),
            "video model": form("set_video_model"),
            "guest agent": form("set_guest_agent"),
            "clone": bool(doc.xpath("//*[@id='clone']")),
            "snapshots": bool(doc.xpath("//*[@id='snapshots']")),
        }
        return {name for name, present in found.items() if present}



class PageControlsTestCase(PageControls, TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_page_scripts_parse(self):
        superuser = get_user_model().objects.create_superuser("ctl_js", "ctl_js@example.com", "x")
        viewer = self.user("ctl_js_viewer", perms=("view_instances",))
        for user in (superuser, viewer):
            self.controls(user)
            scripts = lxml_html.fromstring(self.last_page).xpath("//script[not(@src)]/text()")
            for number, script in enumerate(scripts):
                with self.subTest(user=user.username, script=number):
                    result = subprocess.run(
                        ["node", "--check", "-"], input=script, capture_output=True, text=True, timeout=30
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_header_names_the_vm_its_place_and_resources(self):
        """Host links for administrators, the VM list for its owner; the
        guest agent's state in words; each disk with its device name."""
        disks = [{"dev": "vda", "size": 2 << 30}, {"dev": "vdb", "size": 1 << 30}]
        with patch.object(Instance, "disks", new_callable=PropertyMock, return_value=disks), \
                patch.object(Instance, "guest_agent", new_callable=PropertyMock, return_value=True), \
                patch.object(Instance, "guest_agent_ready", new_callable=PropertyMock, return_value=False):
            self.controls(get_user_model().objects.create_superuser("hdr-admin", "a@example.com", "x"))
            admin_page = lxml_html.fromstring(self.last_page)
            self.controls(self.user("hdr-owner", owner={}))
            owner_page = lxml_html.fromstring(self.last_page)
        links = "//nav[@aria-label='Location']/a"
        self.assertEqual([a.text_content().strip() for a in admin_page.xpath(links)], ["ctl-compute", "Instances"])
        self.assertEqual([a.text_content().strip() for a in owner_page.xpath(links)], ["Instances"])
        self.assertIn("Guest agent not connected", self.last_page)
        self.assertIn("vda 2.0\xa0GB · vdb 1.0\xa0GB", self.last_page)
        self.assertEqual(owner_page.xpath("normalize-space(//dt[.='IPv4']/following-sibling::dd)"), "—")

    def test_superuser_sees_every_control(self):
        superuser = get_user_model().objects.create_superuser("ctl_super", "ctl_super@example.com", "x")
        self.assertEqual(
            self.controls(superuser),
            CONSOLE | POWER | CHANGE | SUPERUSER_ONLY
            | {"clone", "snapshots", "console settings", "destroy", "host links"},
        )

    def test_the_job_panel_gets_the_jobs_just_submitted_once(self):
        superuser = get_user_model().objects.create_superuser("ctl_jobs", "ctl_jobs@example.com", "x")
        self.client.force_login(superuser)
        session = self.client.session
        other = {"resource": "instance:aaaaaaaa-bbbb-cccc-0000-111111111111", "id": "4343"}
        session["operations_shown"] = [{"resource": f"instance:{self.instance.uuid}", "id": "4242"}, other]
        session.save()
        self.controls(superuser)
        self.assertIn('["4242"]', self.last_page)
        self.assertNotIn('"4343"', self.last_page)
        # a job remembered for another VM waits for that VM's page
        self.assertEqual(self.client.session["operations_shown"], [other])
        self.controls(superuser)
        self.assertNotIn('"4242"', self.last_page)

    def test_global_viewers_see_nothing_to_act_on(self):
        perms = ("view_instances", "clone_instances", "snapshot_instances")
        for user in (self.user("ctl_viewer", perms=perms), self.user("ctl_staff", staff=True, perms=perms)):
            with self.subTest(user=user.username):
                self.assertEqual(self.controls(user), set())

    def test_owner_without_change_powers_and_opens_the_console(self):
        owner = self.user("ctl_owner", perms=("clone_instances", "snapshot_instances"), owner={})
        self.assertEqual(self.controls(owner), CONSOLE | POWER)

    def test_owner_with_change_gets_change_clone_and_snapshots(self):
        changer = self.user("ctl_changer", perms=("clone_instances", "snapshot_instances"),
                            owner={"is_change": True})
        self.assertEqual(self.controls(changer), CONSOLE | POWER | CHANGE | {"clone", "snapshots"})

    def test_a_paused_vm_can_be_destroyed(self):
        # destroy stops a paused VM like a running one
        owner = self.user("paused_deleter", owner={"is_delete": True})
        self.assertIn("destroy", self.controls(owner, status=3))

    def test_disks_grow_while_running_paused_or_shut_off(self):
        # QEMU grows a running or paused VM's disk itself (blockResize)
        changer = self.user("disk_resizer", owner={"is_change": True})
        for status, enabled in ((1, True), (3, True), (5, True), (7, False)):
            with self.subTest(status=status):
                self.controls(changer, status=status)
                buttons = lxml_html.fromstring(self.last_page).xpath(
                    "//form[@action=$a]//button[@type='submit']",
                    a=reverse("instances:resize_disk", args=[self.instance.id]),
                )
                self.assertEqual(bool(buttons), enabled)

    def test_a_running_paused_or_shut_off_vm_can_be_cloned(self):
        changer = self.user("vm_cloner", perms=("clone_instances",), owner={"is_change": True})
        for status, enabled in ((1, True), (3, True), (5, True), (4, False)):
            with self.subTest(status=status):
                self.controls(changer, status=status)
                buttons = lxml_html.fromstring(self.last_page).xpath(
                    "//form[@action=$a]//button[@type='submit']",
                    a=reverse("instances:clone", args=[self.instance.id]),
                )
                self.assertEqual(bool(buttons), enabled)

    def test_owner_with_change_and_no_extra_permissions(self):
        changer = self.user("ctl_plain_changer", owner={"is_change": True})
        self.assertEqual(self.controls(changer), CONSOLE | POWER | CHANGE)


class TemplatePageControlsTestCase(PageControls, TestCase):
    def setUp(self):
        super().setUp()
        self.instance.is_template = True
        self.instance.save()

    def test_a_template_is_cloned_by_viewing_it(self):
        viewer = self.user("tpl_viewer", perms=("view_instances", "clone_instances"))
        self.assertEqual(self.controls(viewer, status=5), {"clone"})

    def test_only_staff_owners_change_a_template(self):
        owner = self.user("tpl_plain_changer", owner={"is_change": True})
        staff = self.user("tpl_staff_owner", staff=True, owner={"is_change": True})
        self.assertEqual(self.controls(owner, status=5) & CHANGE, set())
        self.assertEqual(self.controls(staff, status=5) & CHANGE, CHANGE)

    def test_console_settings_of_a_template_are_for_staff_owners(self):
        flags = {"is_change": True, "is_vnc": True}
        owner = self.user("tpl_vnc_owner", owner=flags)
        staff = self.user("tpl_vnc_staff", staff=True, owner=flags)
        self.assertNotIn("console settings", self.controls(owner, status=5))
        self.assertIn("console settings", self.controls(staff, status=5))

    def test_only_staff_owners_destroy_a_template(self):
        owner = self.user("tpl_deleter", owner={"is_delete": True})
        staff = self.user("tpl_staff_deleter", staff=True, owner={"is_delete": True})
        self.assertNotIn("destroy", self.controls(owner, status=5))
        self.assertIn("destroy", self.controls(staff, status=5))

    def test_snapshots_of_a_template_are_for_staff_owners(self):
        perms = ("clone_instances", "snapshot_instances")
        owner = self.user("tpl_changer", perms=perms, owner={"is_change": True})
        staff = self.user("tpl_staff_changer", staff=True, perms=perms, owner={"is_change": True})
        self.assertNotIn("snapshots", self.controls(owner, status=5))
        self.assertIn("snapshots", self.controls(staff, status=5))


class TemplateSnapshotRuleTestCase(PageControls, TestCase):
    """The backend side of the template rule: only staff owners (and
    superusers) take a snapshot of a template; other owners with is_change
    and snapshot_instances are turned away without a libvirt call."""

    def setUp(self):
        super().setUp()
        self.instance.is_template = True
        self.instance.save()

    def snapshot(self, user):
        self.client.force_login(user)
        with patch("instances.models.wvmInstance"), patch("instances.jobs.wvmInstance") as mock_wvm:
            mock_wvm.return_value.instance.snapshotListNames.return_value = []
            self.client.post(
                reverse("instances:snapshot", args=[self.instance.id]),
                {"name": "s1", "description": "", "submission_key": "key-snap0001"},
            )
            return Operation.objects.filter(kind="snapshot.create").exists()

    def test_only_staff_owners_snapshot_a_template(self):
        perms = ("snapshot_instances",)
        owner = self.user("snap_changer", perms=perms, owner={"is_change": True})
        staff = self.user("snap_staff_changer", staff=True, perms=perms, owner={"is_change": True})
        self.assertFalse(self.snapshot(owner))
        self.assertTrue(self.snapshot(staff))
