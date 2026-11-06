import os

from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.db import transaction


def admin_password_path():
    from django.conf import settings

    return os.path.join(str(settings.BASE_DIR), "data", "admin_password")


def _migrated(state_apps, model, field=None):
    """post_migrate follows every migrate, also targeted ones and rollbacks:
    act only once the post-migration state has the model (and field)."""
    if state_apps is None:
        return False
    try:
        fields = state_apps.get_model(model)._meta.get_fields()
    except LookupError:
        return False
    return field is None or any(f.name == field for f in fields)


def grant_change_password(sender, instance, created, raw=False, **kwargs):
    """New users may change their own password unless an admin takes the
    permission away; the user form saves its own choice after this."""
    if not created or raw:
        return
    from django.contrib.auth.models import Permission

    permission = Permission.objects.filter(content_type__app_label="accounts", codename="change_password").first()
    if permission is not None:  # created by post_migrate on a fresh database
        instance.user_permissions.add(permission)


def _store_generated_password(password):
    """
    Write the generated admin password to data/admin_password (mode 0600)
    instead of printing it, so it does not end up in install logs or
    `docker logs`. Abort provisioning if private storage fails.
    """
    path = admin_password_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Never write through a pre-existing file or symlink (this runs as
        # root in Docker, while data/ belongs to www-data).
        if os.path.lexists(path):
            os.unlink(path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(password + "\n")
        print(f"\033[1m* \033[93mGenerated admin password written to {path}\033[0m")
    except OSError as err:
        raise RuntimeError(
            f"Cannot securely store the generated admin password at {path}. "
            "Fix the data directory permissions and run migrate again."
        ) from err


def create_admin(sender, **kwargs):
    """
    Create initial admin user
    """
    import os
    import secrets
    from django.contrib.auth.models import User

    from accounts.models import UserAttributes

    # Any real migrate run provisions while no user exists, so a run that
    # failed to store the password can simply be repeated. flush (used by
    # tests) sends plan=None.
    if kwargs.get("plan") is None:
        return
    state_apps = kwargs.get("apps")
    if not (_migrated(state_apps, "auth.User") and _migrated(state_apps, "accounts.UserAttributes", "must_change_password")):
        return
    if User.objects.exists():
        return

    admin_user = os.environ.get("ADMIN_USERNAME", "admin")
    admin_pass = os.environ.get("ADMIN_PASSWORD")
    generated_password = not admin_pass

    if generated_password:
        admin_pass = secrets.token_urlsafe(16)
        _store_generated_password(admin_pass)

    print(f"\033[1m* \033[92mCreating default admin user '{admin_user}'\033[0m")
    with transaction.atomic():
        admin = User.objects.create_superuser(admin_user, None, admin_pass)
        UserAttributes.objects.create(
            user=admin,
            must_change_password=generated_password,
            max_instances=-1,
            max_cpus=-1,
            max_memory=-1,
            max_disk_size=-1,
        )


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = "Accounts"

    def ready(self):
        post_migrate.connect(create_admin, sender=self)
        from django.conf import settings
        from django.db.models.signals import post_save

        post_save.connect(grant_change_password, sender=settings.AUTH_USER_MODEL)
        from . import checks  # noqa: F401
