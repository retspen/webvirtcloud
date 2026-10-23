"""Changes to users and groups write rows on the Logs page."""

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse

from logs.models import Logs

ATTRIBUTES = {"max_instances": 2, "max_cpus": 2, "max_memory": 2048, "max_disk_size": 20}


def rows():
    return list(Logs.objects.order_by("id").values_list("message", "success"))


class UserRowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("audit-admin", "audit@example.com", "pw")
        self.client.force_login(self.admin)
        Logs.objects.all().delete()  # the login's row

    def create(self, username="carol", **extra):
        return self.client.post(reverse("admin:user_create"),
                                {"username": username, "password": "Carol-pass-2026", "is_active": "on", **ATTRIBUTES, **extra})

    def edit(self, user, **changes):
        data = {"username": user.username, "email": user.email, "is_active": "on", **ATTRIBUTES,
                "user_permissions": [p.pk for p in user.user_permissions.all()],
                "groups": [g.pk for g in user.groups.all()], **changes}
        return self.client.post(reverse("admin:user_update", args=[user.pk]), data)

    def test_user_add_change_delete(self):
        self.create()
        carol = User.objects.get(username="carol")
        self.edit(carol, email="carol@example.com")
        self.edit(User.objects.get(pk=carol.pk))  # nothing changed
        self.client.post(reverse("admin:user_delete", args=[carol.pk]))
        self.assertEqual(rows(), [
            ("User carol: add", True),
            ("User carol: change email", True),
            ("User carol: delete", True),
        ])

    def test_attributes_and_groups_are_named(self):
        self.create()
        carol = User.objects.get(username="carol")
        permission = Permission.objects.get(content_type__app_label="accounts", codename="change_password")
        carol.user_permissions.remove(permission)
        Logs.objects.all().delete()

        self.edit(carol, max_instances=5)
        group = Group.objects.create(name="ops")
        self.edit(carol, max_instances=5, groups=[group.pk], user_permissions=[permission.pk])
        self.edit(carol, max_instances=5, groups=[group.pk], user_permissions=[permission.pk], username="carla")
        self.edit(User.objects.get(pk=carol.pk), username="")  # invalid: no row
        self.assertEqual([m for m, _ in rows()], [
            "User carol: change max_instances",
            "User carol: change groups, user_permissions",
            "User carol: change username",
        ])
        self.assertTrue(User.objects.get(pk=carol.pk).user_permissions.filter(pk=permission.pk).exists())

    def test_block_unblock_and_password(self):
        self.create()
        carol = User.objects.get(username="carol")
        Logs.objects.all().delete()
        self.client.post(reverse("admin:user_block", args=[carol.pk]))
        self.client.post(reverse("admin:user_block", args=[carol.pk]))  # already blocked: nothing changes
        self.client.post(reverse("admin:user_unblock", args=[carol.pk]))
        self.client.post(reverse("admin:user_unblock", args=[carol.pk]))
        self.client.post(reverse("admin:user_update_password", args=[carol.pk]),
                         {"password1": "New-carol-pass-1", "password2": "New-carol-pass-1"})
        self.assertEqual(rows(), [
            ("User carol: block", True),
            ("User carol: unblock", True),
            ("User carol: set password", True),
        ])
        self.assertFalse(Logs.objects.filter(message__contains="New-carol-pass-1").exists())

    @override_settings(NEW_USER_DEFAULT_INSTANCES=["no-such-vm"])
    def test_a_failing_default_vm_leaves_no_user(self):
        from instances.models import Instance
        with self.assertRaises(Instance.DoesNotExist):
            self.create()
        self.assertFalse(User.objects.filter(username="carol").exists())
        self.assertEqual(rows(), [("User carol: add: DoesNotExist", False)])

    def test_the_row_has_actor_and_ip(self):
        self.client.post(
            reverse("admin:user_create"), {"username": "carol", "password": "Carol-pass-2026", **ATTRIBUTES},
            REMOTE_ADDR="192.0.2.9")
        row = Logs.objects.get()
        self.assertEqual((row.user, row.host, row.instance, row.ip), ("audit-admin", "-", "", "192.0.2.9"))


class GroupAndRemovedVMRowTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("audit-admin", "audit@example.com", "pw"))
        Logs.objects.all().delete()  # the login's row

    def test_group_add_change_delete(self):
        member = User.objects.create_user("dave")
        permission = Permission.objects.get(content_type__app_label="accounts", codename="change_password")
        self.client.post(reverse("admin:group_create"), {"name": "ops"})
        group = Group.objects.get(name="ops")
        url = reverse("admin:group_update", args=[group.pk])
        self.client.post(url, {"name": "ops", "users": [member.pk]})
        self.client.post(url, {"name": "ops", "users": [member.pk], "permissions": [permission.pk]})
        self.client.post(url, {"name": "ops", "users": [member.pk], "permissions": [permission.pk]})  # no change
        self.client.post(reverse("admin:group_delete", args=[group.pk]))
        self.assertEqual(rows(), [
            ("Group ops: add", True),
            ("Group ops: change users", True),
            ("Group ops: change permissions", True),
            ("Group ops: delete", True),
        ])

    def test_a_removed_vm_record_delete(self):
        from instances.models import InstanceTombstone
        uuid = "55555555-5555-5555-5555-555555555555"
        tombstone = InstanceTombstone.objects.create(uuid=uuid, name="vm", owners=[])
        self.client.post(reverse("admin:tombstone_delete", args=[tombstone.pk]))
        self.assertEqual(rows(), [(f"Removed VM vm ({uuid}): delete", True)])
