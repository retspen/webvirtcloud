from django.apps import AppConfig
from django.db.models.signals import post_migrate


def apply_change_password(sender, **kwargs):
    """
    Apply new change_password permission for all users
    Depending on settings SHOW_PROFILE_EDIT_PASSWORD
    """
    from django.conf import settings
    from django.contrib.auth.models import Permission, User

    if hasattr(settings, "SHOW_PROFILE_EDIT_PASSWORD"):
        print("\033[1m! \033[92mSHOW_PROFILE_EDIT_PASSWORD is found inside settings.py\033[0m")
        print("\033[1m* \033[92mApplying permission can_change_password for all users\033[0m")
        users = User.objects.all()
        permission = Permission.objects.get(codename="change_password")
        if settings.SHOW_PROFILE_EDIT_PASSWORD:
            print("\033[1m! \033[91mWarning!!! Setting to True for all users\033[0m")
            for user in users:
                user.user_permissions.add(permission)
        else:
            print("\033[1m* \033[91mWarning!!! Setting to False for all users\033[0m")
            for user in users:
                user.user_permissions.remove(permission)
        print("\033[1m! Don`t forget to remove the option from settings.py\033[0m")


def create_admin(sender, **kwargs):
    """
    Create initial admin user
    """
    from django.contrib.auth.models import User

    from accounts.models import UserAttributes

    plan = kwargs.get("plan", [])
    for migration, rolled_back in plan:
        if (
            migration.app_label == "accounts"
            and migration.name == "0001_initial"
            and not rolled_back
        ):
            if User.objects.count() == 0:
                print("\033[1m* \033[92mCreating default admin user\033[0m")
                admin = User.objects.create_superuser("admin", None, "admin")
                UserAttributes(
                    user=admin,
                    max_instances=-1,
                    max_cpus=-1,
                    max_memory=-1,
                    max_disk_size=-1,
                ).save()
            break


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = "Accounts"

    def ready(self):
        post_migrate.connect(create_admin, sender=self)
        post_migrate.connect(apply_change_password, sender=self)
