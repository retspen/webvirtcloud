"""Every libvirt state has a label, and the lists offer the actions the state
and the user's permissions allow."""

from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

from accounts.models import UserInstance
from appsettings.models import AppSettings
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from instances.states import allowed_actions
from lxml import html

LABELS = {0: "No state", 1: "Active", 2: "Blocked", 3: "Suspended", 4: "Shutting down", 5: "Off", 6: "Crashed", 7: "PM suspended"}
# actions offered per state, for a superuser
ACTIONS = {
    0: set(),
    1: {"poweroff", "powercycle", "force_off", "suspend"},
    2: {"poweroff", "powercycle", "force_off", "suspend"},
    3: {"resume", "force_off"},
    4: {"force_off"},
    5: {"poweron"},
    6: {"force_off"},
    7: {"force_off"},
}
ALL = {"poweron", "poweroff", "powercycle", "force_off", "suspend", "resume"}


class Domain:
    def __init__(self, state):
        self.state = state

    def info(self):
        return [self.state, 4194304, 2097152, 2, 0]


class StateTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("st-admin", "st@example.com", "pw")
        self.owner = User.objects.create_user("st-owner", password="pw")
        self.viewer = User.objects.create_user("st-viewer", password="pw")
        self.viewer.user_permissions.add(Permission.objects.get(codename="view_instances"))
        self.compute = Compute.objects.create(name="st", hostname="10.0.0.1", login="u", password="p", type=1)
        self.vms = {}
        for state in LABELS:
            vm = Instance.objects.create(compute=self.compute, name=f"st-vm-{state}", uuid=f"{state:08d}-0000-0000-0000-000000000000")
            UserInstance.objects.create(user=self.owner, instance=vm)
            self.vms[state] = vm
        AppSettings.objects.filter(key="VIEW_INSTANCES_LIST_STYLE").update(value="nongrouped")

    def get(self, user, url):
        by_uuid = {vm.uuid: state for state, vm in self.vms.items()}

        def wvm(*args, uuid=None, **kwargs):
            return SimpleNamespace(instance=Domain(by_uuid[uuid]), get_title=lambda: "", get_uuid=lambda: uuid)

        self.client.force_login(user)
        props = {"status": True, "connection_error": None, "cpu_count": 1, "ram_size": 1, "ram_usage": 0}
        patches = [patch.object(Compute, k, new_callable=PropertyMock, return_value=v) for k, v in props.items()]
        patches += [patch("instances.views.utils.refr"), patch("computes.views.utils.refresh_instance_database"),
                    patch("instances.models.wvmInstance", side_effect=wvm)]
        for p in patches:
            p.start()
        try:
            response = self.client.get(url)
        finally:
            for p in reversed(patches):
                p.stop()
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def offered(self, page, vm):
        return {a for a in ALL if reverse(f"instances:{a}", args=[vm.id]) in page}

    def test_every_state_has_a_label(self):
        page = self.get(self.admin, reverse("instances:index"))
        for state, label in LABELS.items():
            with self.subTest(state=state):
                self.assertIn(f">{label}<", page)

    def test_superuser_actions_follow_the_state(self):
        for url in (reverse("instances:index"), reverse("instances", args=[self.compute.id])):
            page = self.get(self.admin, url)
            for state, vm in self.vms.items():
                with self.subTest(url=url, state=state):
                    self.assertEqual(self.offered(page, vm), ACTIONS[state])

    def test_forced_power_actions_in_the_lists_ask_first(self):
        # one click in a list row would cut the VM off as a power failure does
        for url in (reverse("instances:index"), reverse("instances", args=[self.compute.id])):
            page = html.fromstring(self.get(self.admin, url))
            for state, vm in self.vms.items():
                for action in {"force_off", "powercycle"} & ACTIONS[state]:
                    button = page.xpath(f"//form[@action='{reverse(f'instances:{action}', args=[vm.id])}']//button")[0]
                    with self.subTest(url=url, vm=vm.name, action=action):
                        self.assertIsNone(button.get("onclick"))  # the page's dialog asks, not the browser
                        self.assertIn(vm.name, button.get("data-confirm"))
                        self.assertIn("power cut", button.get("data-confirm"))

    def test_owner_is_not_offered_suspend_or_resume(self):
        # both views are for superusers only; a VM an administrator suspended
        # stays as it is for its owner, as on the VM page
        page = self.get(self.owner, reverse("instances:index"))
        for state, vm in self.vms.items():
            with self.subTest(state=state):
                expected = set() if state == 3 else ACTIONS[state] - {"suspend", "resume"}
                self.assertEqual(self.offered(page, vm), expected)

    def test_a_viewer_who_owns_nothing_is_offered_no_actions(self):
        page = self.get(self.viewer, reverse("instances:index"))
        for state, vm in self.vms.items():
            with self.subTest(state=state):
                self.assertIn(vm.name, page)
                self.assertEqual(self.offered(page, vm), set())


    def test_the_list_offers_each_state_and_marks_each_row_and_host(self):
        # static/js/table_filter.js filters by these (test_table_filter_js)
        AppSettings.objects.filter(key="VIEW_INSTANCES_LIST_STYLE").update(value="grouped")
        page = html.fromstring(self.get(self.admin, reverse("instances:index")))
        # a pill for all and for each state, every state kept (table_filter.js hides the empty ones)
        pills = page.xpath("//div[@id='state-pills']/button/@data-pill-state")
        self.assertEqual(pills, ["", *LABELS.values(), "Unknown"])
        marks = page.xpath("//tbody[@data-host='st']//tr//@data-state")
        self.assertEqual(marks, list(LABELS.values()))
        # the host row stays on top of its VMs; memory and vCPUs sort as numbers
        rows = page.xpath("//tbody[@data-host='st']/tr")
        self.assertEqual(rows[0].get("data-sort-method"), "none")
        self.assertEqual([r.xpath("td[@data-sort]/@data-sort") for r in rows[1:2]], [["2", "2097152"]])


    def row_group(self, page, state):
        url = reverse("instances:instance", args=[self.vms[state].id])
        return page.xpath(f"//tr[.//a[@href='{url}']]//div[@role='group']")

    @staticmethod
    def enabled(group):
        return [c.get("aria-label") for c in group.xpath(".//*[contains(@class,'btn-sm')]") if c.get("disabled") is None]

    def test_each_row_has_the_same_group_its_state_s_actions_enabled(self):
        # console, the power action, the menu, in every row: those that do not apply now disabled
        page = html.fromstring(self.get(self.admin, reverse("instances:index")))
        power = {"poweron": "Start", "resume": "Resume", "poweroff": "Shut down"}
        in_menu = {"suspend": "Suspend", "force_off": "Force off", "powercycle": "Power cycle"}
        for state, label in LABELS.items():
            vm = self.vms[state]
            with self.subTest(state=label):
                (group,) = self.row_group(page, state)
                self.assertEqual(group.get("aria-label"), f"Actions for {vm.name}")
                self.assertEqual(len(group.xpath(".//*[contains(@class,'btn-sm')]")), 3)
                running = state in (1, 2)
                expected = (["Console"] if running else []) + [power[a] for a in power if a in ACTIONS[state]]
                if ACTIONS[state] & set(in_menu):
                    expected.append("More actions")
                self.assertEqual(self.enabled(group), expected)
                items = [i.text_content().strip() for i in group.xpath(".//*[contains(@class,'dropdown-item')]")]
                self.assertEqual(items, [in_menu[a] for a in in_menu if a in ACTIONS[state]])

    def test_an_owner_sees_the_group_disabled_on_a_vm_an_administrator_paused(self):
        page = html.fromstring(self.get(self.owner, reverse("instances:index")))
        (group,) = self.row_group(page, 3)
        self.assertEqual(self.enabled(group), [])
        self.assertTrue(group.xpath(".//button[@aria-label='Resume'][@disabled]"))
        # a user who only views VMs gets no group
        page = html.fromstring(self.get(self.viewer, reverse("instances:index")))
        self.assertEqual(len(page.xpath("//tbody//tr[@data-search]")), len(self.vms))
        self.assertEqual(page.xpath("//div[@role='group']"), [])

    def test_rows_are_searched_for_their_vm_not_their_buttons(self):
        # table_filter.js searches data-search: a menu's "Force off" would match "off" in every row
        for style in ("grouped", "nongrouped"):
            AppSettings.objects.filter(key="VIEW_INSTANCES_LIST_STYLE").update(value=style)
            page = html.fromstring(self.get(self.admin, reverse("instances:index")))
            searched = page.xpath("//tbody//tr/@data-search")
            with self.subTest(style=style):
                self.assertEqual(len(searched), len(self.vms))
                for vm, text in zip(self.vms.values(), searched):
                    self.assertTrue(text.startswith(vm.name), text)
                    self.assertIn("st-owner", text)
                    self.assertNotIn("Force", text)
                self.assertTrue(page.xpath("//div[@id='no-match'][@hidden]//button[@id='clear-filters']"))

    def test_the_lists_show_the_vms_by_name(self):
        # the first VM made comes last by name: the database's own order is not the list's
        Instance.objects.filter(pk=self.vms[0].pk).update(name="st-vm-9")
        by_name = [LABELS[state] for state in [*list(LABELS)[1:], 0]]
        for style in ("grouped", "nongrouped"):
            AppSettings.objects.filter(key="VIEW_INSTANCES_LIST_STYLE").update(value=style)
            page = html.fromstring(self.get(self.admin, reverse("instances:index")))
            with self.subTest(style=style):
                self.assertEqual(page.xpath("//tbody//tr//@data-state"), by_name)
        page = html.fromstring(self.get(self.admin, reverse("instances", args=[self.compute.id])))
        names = [name.strip() for name in page.xpath("//tbody//tr//a[starts-with(normalize-space(), 'st-vm-')]/text()")]
        self.assertEqual(names, sorted(names))


class DetailStateTests(TestCase):
    """The VM page names every state and offers a forced power off where only that helps."""

    def test_states(self):
        owner = get_user_model().objects.create_user("st-detail-owner", password="pw")
        compute = Compute.objects.create(name="st-d", hostname="10.0.0.2", login="u", password="p", type=1)
        vm = Instance.objects.create(compute=compute, name="st-d-vm", uuid="99999999-0000-0000-0000-00000000d000")
        UserInstance.objects.create(user=owner, instance=vm, is_change=True)
        self.client.force_login(owner)
        badge = LABELS
        force_off = reverse("instances:force_off", args=[vm.id])
        poweroff = reverse("instances:poweroff", args=[vm.id])
        for state, label in badge.items():
            with self.subTest(state=state), patch("instances.models.wvmInstance") as wvm, patch.object(
                Compute, "status", new_callable=PropertyMock, return_value=True
            ):
                proxy = wvm.return_value
                proxy.get_memory.return_value = 1024
                proxy.get_cur_memory.return_value = 1024
                proxy.get_max_memory.return_value = 4096
                for name in ("get_networks", "get_ifaces", "get_storages", "get_disk_devices", "get_media_devices", "get_net_devices"):
                    getattr(proxy, name).return_value = []
                proxy.get_hostdevs.return_value = ([], [], [])
                proxy.get_status.return_value = state
                page = self.client.get(reverse("instances:instance", args=[vm.id])).content.decode()
                self.assertIn(f'">{label}</span>', page.replace("\n", "").replace("  ", ""))
                self.assertEqual(poweroff in page, state in (1, 2))
                self.assertEqual(force_off in page, state in (1, 2, 4, 6, 7))


class AllowedActionsTests(TestCase):
    """The rules themselves, without templates."""

    def test_rules(self):
        User = get_user_model()
        admin = User.objects.create_superuser("aa-admin", "aa@example.com", "pw")
        owner = User.objects.create_user("aa-owner", password="pw")
        other = User.objects.create_user("aa-other", password="pw")
        compute = Compute.objects.create(name="aa", hostname="10.0.0.3", login="u", password="p", type=1)
        vm = Instance.objects.create(compute=compute, name="aa-vm", uuid="aaaaaaaa-0000-0000-0000-000000000000")
        UserInstance.objects.create(user=owner, instance=vm)
        for state in LABELS:
            with self.subTest(state=state):
                self.assertEqual(allowed_actions(admin, vm, state) - {"console"}, ACTIONS[state])
                expected = set() if state == 3 else ACTIONS[state] - {"suspend", "resume"}
                self.assertEqual(allowed_actions(owner, vm, state) - {"console"}, expected)
                self.assertEqual(allowed_actions(other, vm, state), set())


class TemplatePowerTests(TestCase):
    """A running template is not power cycled: that would start it again."""

    def test_a_running_template_has_no_power_cycle(self):
        admin = get_user_model().objects.create_superuser("tp-admin", "tp@example.com", "pw")
        compute = Compute.objects.create(name="tp", hostname="10.0.0.5", login="u", password="p", type=1)
        vm = Instance.objects.create(compute=compute, name="tp-vm", uuid="dddddddd-0000-0000-0000-000000000000", is_template=True)
        self.assertEqual(allowed_actions(admin, vm, 1) - {"console"}, ACTIONS[1] - {"powercycle"})


class TemplateCloneTests(TestCase):
    """A shut-off template offers Clone to whoever may clone it, owner or not."""

    def test_clone_link(self):
        User = get_user_model()
        compute = Compute.objects.create(name="tc", hostname="10.0.0.4", login="u", password="p", type=1)
        vm = Instance.objects.create(compute=compute, name="tc-vm", uuid="cccccccc-0000-0000-0000-000000000000", is_template=True)
        cloner = User.objects.create_user("tc-viewer", password="pw")
        cloner.user_permissions.add(*Permission.objects.filter(codename__in=["view_instances", "clone_instances"]))
        cloner = User.objects.get(pk=cloner.pk)  # no cached permissions
        owner = User.objects.create_user("tc-owner", password="pw")
        UserInstance.objects.create(user=owner, instance=vm)
        admin = User.objects.create_superuser("tc-admin", "tc@example.com", "pw")
        self.assertEqual(allowed_actions(cloner, vm, 5), {"clone"})
        self.assertEqual(allowed_actions(admin, vm, 5), {"clone"})
        self.assertEqual(allowed_actions(owner, vm, 5), set())  # no clone permission


class EmptyListTests(TestCase):
    def test_a_user_without_vms_is_told_so(self):
        self.client.force_login(get_user_model().objects.create_user("st-nobody", password="pw"))
        response = self.client.get(reverse("instances:index"))
        self.assertContains(response, "There are no VMs here yet.")
        self.assertNotContains(response, "searchable")  # no VM table
