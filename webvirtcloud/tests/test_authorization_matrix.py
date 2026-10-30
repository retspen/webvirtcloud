"""
Authorization matrix.

Walks every named URL pattern and checks that an authenticated user without
any relation to a VM or compute cannot reach it, unless the URL is in the
explicit allowlist below. It then checks, per role (global view_instances,
staff, owners with no flags / is_change / is_delete / is_vnc), that exactly
the expected set of VM URLs passes authorization. A new endpoint added without an authorization check
makes this test fail, so the allowlist must be extended deliberately. This
is an authorization test, not an operation-success test; the real test-driver
regressions separately assert successful disk edits, cloning and power actions.

Limitation: the compute points at a closed port, so a view that turns a
libvirt connection error into 404 looks "denied" here even without an
authorization check. Endpoints where that matters (consoles) get dedicated
tests with libvirt mocked.
"""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction
from django.test import Client, TestCase
from django.urls import NoReverseMatch, URLPattern, URLResolver, get_resolver, resolve, reverse

from accounts.models import UserInstance, UserSSHKey
from computes.models import Compute
from instances.models import Instance

# URL name -> why any authenticated user may reach it.
ALLOWED_FOR_ANY_USER = {
    "index": "landing page",
    "instances:index": "lists only the user's own instances",
    "instances:find_address": "searches only the user's own instances",
    "accounts:login": "login page",
    "accounts:email_otp": "part of the login flow (its own issues are tracked separately)",
    "accounts:logout": "logout",
    "accounts:profile": "the user's own profile",
    "accounts:change_password": "the user's own password; new users get the permission by default",
    "accounts:ssh_key_create": "the user's own SSH keys",
    "accounts:api_token_create": "the user's own API tokens",
    "accounts:api_token_created": "the token the user just created, from their own session",
    "set_language": "UI language switch",
    "console": "renders an error without a valid token; access is checked per VM",
    "ds_openstack_index": "cloud-init datasource, fetched by VMs",
    "ds_openstack_metadata": "cloud-init datasource, fetched by VMs",
    "ds_openstack_userdata": "cloud-init datasource, fetched by VMs",
    "instance-list": "API: filtered to the user's own instances",
    "compute-instance-list": "API: filtered to the user's own instances",
    "instance-flavor-list": "API: flavor catalogue",
    "instance-flavor-detail": "API: flavor catalogue",
    "operation-list": "API: filtered to the user's own jobs",
    "operation-resource": "API: checks per resource who may see it",
    "operations:jobs": "lists only the user's own jobs",
    "schema": "API docs: any authenticated user (SERVE_PERMISSIONS)",
    "schema-json": "API docs: any authenticated user (SERVE_PERMISSIONS)",
    "schema-redoc": "API docs: any authenticated user (SERVE_PERMISSIONS)",
    "schema-swagger-ui": "API docs: any authenticated user (SERVE_PERMISSIONS)",
}

# URL name -> why an anonymous visitor may reach it. Everything else must
# redirect to the login page.
ALLOWED_FOR_ANONYMOUS = {
    "accounts:login": "login page",
    "accounts:email_otp": "part of the login flow (its own issues are tracked separately)",
    "ds_openstack_index": "cloud-init datasource, fetched by VMs that do not log in",
    "ds_openstack_metadata": "cloud-init datasource, fetched by VMs that do not log in",
    "ds_openstack_userdata": "cloud-init datasource, fetched by VMs that do not log in",
}

# Endpoints that expose a VM's console (or its VNC password) and therefore
# must follow the console rule: superuser or VM owner, not global view_instances.
CONSOLE_ENDPOINTS = ["instances:getvvfile", "vdi_url"]

DENIED = (403, 404)

# Per-role reachability on the test VM, outside ALLOWED_FOR_ANY_USER. Compared
# in both directions: an extra URL is a privilege leak, a missing one is a
# regression. Must match the roles table in README.md.
VIEW_VM = {
    "instances:instance",
    "instances:status",
    "instances:stats",
    "instances:osinfo",
    "instances:sshkeys",
    "instance-detail",
    "compute-instance-detail",
}
POWER_AND_CONSOLE = {
    "instances:poweron",
    "instances:poweroff",
    "instances:powercycle",
    "instances:force_off",
    "compute-instance-poweron",
    "compute-instance-poweroff",
    "compute-instance-powercycle",
    "compute-instance-forceoff",
    "instances:getvvfile",
    # vdi_url is also allowed for owners, but answers 404 here because the
    # test compute is unreachable; see the console rule tests.
}
CHANGE_VM = {
    "instances:resizevm_cpu",
    "instances:resize_memory",
    "instances:resize_disk",
    "instances:rootpasswd",
    "instances:add_public_key",
    "instances:change_options",
}
# Also needs is_vnc (can_manage_console). Snapshots also need
# instances.snapshot_instances, which no role here has: refused to all.
CONSOLE_SETTINGS = {"instances:update_console"}
# Also needs is_staff: whether the VM is a template.
TEMPLATE_FLAG = {"instances:set_template"}
DELETE_VM = {"instances:destroy"}

ROLE_EXPECTATIONS = {
    # role: (is_staff, global view_instances, owner flags or None, expected URLs)
    "view_instances": (False, True, None, VIEW_VM),
    "staff_with_view_instances": (True, True, None, VIEW_VM),
    "owner": (False, False, {}, VIEW_VM | POWER_AND_CONSOLE),
    "owner_is_change": (False, False, {"is_change": True}, VIEW_VM | POWER_AND_CONSOLE | CHANGE_VM),
    "owner_is_delete": (False, False, {"is_delete": True}, VIEW_VM | POWER_AND_CONSOLE | DELETE_VM),
    "staff_owner_is_change_is_vnc": (
        True,
        False,
        {"is_change": True, "is_vnc": True},
        VIEW_VM | POWER_AND_CONSOLE | CHANGE_VM | CONSOLE_SETTINGS | TEMPLATE_FLAG,
    ),
}


# A template VM: only superusers and staff owners change or delete it; other
# owners keep view, power (poweron and powercycle are no-ops on a template)
# and console. Cloning has its own rule, see the clone test.
TEMPLATE_ROLE_EXPECTATIONS = {
    **ROLE_EXPECTATIONS,
    "owner_is_change": (False, False, {"is_change": True}, VIEW_VM | POWER_AND_CONSOLE),
    "owner_is_delete": (False, False, {"is_delete": True}, VIEW_VM | POWER_AND_CONSOLE),
}


def iter_patterns(patterns, prefix="", params=None):
    params = params or {}
    for p in patterns:
        own = {**{g: None for g in p.pattern.regex.groupindex}, **p.pattern.converters}
        if isinstance(p, URLResolver):
            ns = f"{prefix}{p.namespace}:" if p.namespace else prefix
            yield from iter_patterns(p.url_patterns, ns, {**params, **own})
        elif isinstance(p, URLPattern) and p.name:
            yield prefix + p.name, {**params, **own}


class AuthorizationMatrixTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="matrix_plain", password="x")
        self.viewer = User.objects.create_user(username="matrix_viewer", password="x")
        self.viewer.user_permissions.add(Permission.objects.get(codename="view_instances"))
        # Port 1 is closed, so any view that reaches libvirt fails fast.
        self.compute = Compute.objects.create(
            name="matrix-compute", hostname="127.0.0.1:1", login="root", password="", type=1
        )
        self.instance = Instance.objects.create(
            compute=self.compute,
            name="matrix-vm",
            uuid="22222222-3333-4444-5555-666666666666",
        )
        self.client = Client(raise_request_exception=True)

    def _kwargs(self, params):
        kwargs = {}
        for name, converter in params.items():
            if name in ("compute_id", "compute_pk"):
                kwargs[name] = self.compute.pk
            elif converter is not None and type(converter).__name__ == "UUIDConverter":
                kwargs[name] = "00000000-0000-0000-0000-000000000000"
            elif name in ("pk", "instance_id"):
                kwargs[name] = self.instance.pk if converter else str(self.instance.pk)
            elif name == "vname":
                kwargs[name] = self.instance.name
            elif name == "format":
                kwargs[name] = "json"
            elif name == "version":
                # A real value, so datasource views do not 404 on the parameter.
                kwargs[name] = "latest"
            elif converter is not None and type(converter).__name__ == "IntConverter":
                kwargs[name] = 1
            else:
                kwargs[name] = "x"
        return kwargs

    def _request(self, user, url):
        self.client.force_login(user)
        response = self.client.get(url, HTTP_REFERER=f"/instances/{self.instance.pk}/")
        if response.status_code == 405:
            self.client.force_login(user)
            data = {}
            if url.endswith("/add_public_key/"):
                key, _ = UserSSHKey.objects.get_or_create(
                    user=user, keyname="matrix-key", defaults={"keypublic": "ssh-ed25519 TEST matrix"}
                )
                data["sshkeyid"] = key.pk
            response = self.client.post(url, data, HTTP_REFERER=f"/instances/{self.instance.pk}/")
        if response.status_code >= 500:
            # Only the fixture's explicit libvirt failure is an acceptable
            # authorization outcome. Unexpected failures must fail the test.
            self.assertEqual(response.status_code, 500)
            self.assertTrue(response.context and response.context.get("libvirt_error"))
        return response

    def _url(self, name, params):
        return reverse(name, kwargs=self._kwargs(params))

    def test_plain_user_cannot_reach_anything_outside_the_allowlist(self):
        reachable = []
        for name, params in iter_patterns(get_resolver().url_patterns):
            if name in ALLOWED_FOR_ANY_USER:
                continue
            try:
                url = self._url(name, params)
            except NoReverseMatch:
                reachable.append(f"{name}: cannot build URL, extend _kwargs()")
                continue
            response = self._request(self.user, url)
            if response.status_code not in DENIED:
                reachable.append(f"{name} ({url}) -> {response.status_code}")
        self.assertEqual(
            reachable,
            [],
            "Reachable by a user without any VM/compute relation:\n" + "\n".join(reachable),
        )

    def test_anonymous_visitor_is_sent_to_login_everywhere_else(self):
        from django.conf import settings

        reachable = []
        for name, params in iter_patterns(get_resolver().url_patterns):
            if name in ALLOWED_FOR_ANONYMOUS:
                continue
            url = self._url(name, params)
            for method in (self.client.get, self.client.post):
                self.client.logout()
                response = method(url)
                # DRF views opt out of login middleware and deny by their own
                # permission classes.
                api_denied = hasattr(resolve(url).func, "cls") and response.status_code in (401, 403)
                to_login = response.status_code == 302 and response["Location"].startswith(settings.LOGIN_URL)
                if not (api_denied or to_login):
                    reachable.append(f"{method.__name__.upper()} {name} ({url}) -> {response.status_code}")
        self.assertEqual(reachable, [], "Reachable without logging in:\n" + "\n".join(reachable))

    def test_allowlist_only_names_existing_urls(self):
        names = {name for name, _ in iter_patterns(get_resolver().url_patterns)}
        self.assertEqual(sorted(set(ALLOWED_FOR_ANY_USER) - names), [])

    def test_global_view_permission_does_not_open_consoles(self):
        params = dict(iter_patterns(get_resolver().url_patterns))
        reachable = []
        # Mock libvirt so the views would succeed if authorization let them through.
        with patch("datasource.views.wvmInstance", MagicMock()), patch(
            "datasource.views.get_hostname_by_ip", return_value="host"
        ), patch("instances.models.wvmInstance", MagicMock()):
            for name in CONSOLE_ENDPOINTS:
                url = self._url(name, params[name])
                response = self._request(self.viewer, url)
                if response.status_code not in DENIED:
                    reachable.append(f"{name} ({url}) -> {response.status_code}")
        self.assertEqual(
            reachable,
            [],
            "Console endpoints reachable with only global view_instances:\n"
            + "\n".join(reachable),
        )

    def _make_role_user(self, role, is_staff, view_instances, owner_flags):
        user = get_user_model().objects.create_user(
            username=f"matrix_{role}", password="x", is_staff=is_staff
        )
        if view_instances:
            user.user_permissions.add(Permission.objects.get(codename="view_instances"))
        if owner_flags is not None:
            UserInstance.objects.create(instance=self.instance, user=user, **owner_flags)
        return user

    def _reachable(self, user):
        reachable = set()
        for name, params in iter_patterns(get_resolver().url_patterns):
            if name in ALLOWED_FOR_ANY_USER:
                continue
            url = self._url(name, params)
            # Roll back every request, so e.g. destroy does not remove the VM
            # for the requests that follow.
            with transaction.atomic():
                response = self._request(user, url)
                transaction.set_rollback(True)
            if response.status_code not in DENIED:
                reachable.add(name)
        return reachable

    def test_role_reachability_matches_the_roles_table(self):
        for role, (is_staff, view_instances, owner_flags, expected) in ROLE_EXPECTATIONS.items():
            with self.subTest(role=role):
                user = self._make_role_user(role, is_staff, view_instances, owner_flags)
                reachable = self._reachable(user)
                self.assertEqual(
                    (sorted(reachable - expected), sorted(expected - reachable)),
                    ([], []),
                    f"{role}: (unexpectedly reachable, unexpectedly denied)",
                )

    def test_role_reachability_on_a_template_vm(self):
        self.instance.is_template = True
        self.instance.save()
        for role, (is_staff, view_instances, owner_flags, expected) in TEMPLATE_ROLE_EXPECTATIONS.items():
            with self.subTest(role=role):
                user = self._make_role_user(role, is_staff, view_instances, owner_flags)
                reachable = self._reachable(user)
                self.assertEqual(
                    (sorted(reachable - expected), sorted(expected - reachable)),
                    ([], []),
                    f"template, {role}: (unexpectedly reachable, unexpectedly denied)",
                )

    def test_a_template_is_cloned_by_viewing_it_a_vm_needs_change(self):
        user = self._make_role_user("cloner", False, True, None)
        user.user_permissions.add(Permission.objects.get(codename="clone_instances"))
        url = reverse("instances:clone", args=[self.instance.pk])
        for is_template, reached in ((False, False), (True, True)):
            with self.subTest(is_template=is_template):
                self.instance.is_template = is_template
                self.instance.save()
                with transaction.atomic():
                    response = self._request(user, url)
                    transaction.set_rollback(True)
                self.assertEqual(response.status_code not in DENIED, reached, response.status_code)

    def test_owner_power_actions_succeed_through_web_and_api_with_real_test_driver(self):
        import libvirt
        from vrtManager.instance import wvmInstance

        conn = libvirt.open("test:///default")
        self.addCleanup(conn.close)
        proxy = wvmInstance.__new__(wvmInstance)
        proxy.wvm = conn
        proxy.instance = conn.lookupByName("test")
        was_active = proxy.instance.isActive()

        def restore_power_state():
            if was_active and not proxy.instance.isActive():
                proxy.instance.create()
            elif not was_active and proxy.instance.isActive():
                proxy.instance.destroy()

        self.addCleanup(restore_power_state)
        UserInstance.objects.create(instance=self.instance, user=self.user)
        self.client.force_login(self.user)
        with patch("instances.models.wvmInstance", return_value=proxy):
            response = self.client.post(reverse("instances:poweroff", args=[self.instance.pk]), {})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(proxy.get_status(), libvirt.VIR_DOMAIN_SHUTOFF)
            response = self.client.post(reverse("instances:poweron", args=[self.instance.pk]), {})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(proxy.get_status(), libvirt.VIR_DOMAIN_RUNNING)
            response = self.client.post(
                reverse("compute-instance-poweroff", kwargs={"compute_pk": self.compute.pk, "pk": self.instance.pk}), {}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(proxy.get_status(), libvirt.VIR_DOMAIN_SHUTOFF)
