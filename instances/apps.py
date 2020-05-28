from django.apps import AppConfig
from django.db.models.signals import post_migrate


def migrate_can_clone_instances(sender, **kwargs):
    '''
    Migrate can clone instances user attribute to permission
    '''
    from django.conf import settings
    from django.contrib.auth.models import User, Permission
    from accounts.models import UserAttributes

    plan = kwargs['plan']
    for migration, rolled_back in plan:
        if migration.app_label == 'instances' and migration.name == '0002_permissionset' and not rolled_back:
            users = User.objects.all()
            permission = Permission.objects.get(codename='clone_instances')
            print('\033[92mMigrating can_clone_instaces user attribute to permission')
            for user in users:
                if user.userattributes:
                    if user.userattributes.can_clone_instances:
                        user.user_permissions.add(permission)
            break


class InstancesConfig(AppConfig):
    name = 'instances'
    verbose_name = 'instances'

    def ready(self):
        post_migrate.connect(migrate_can_clone_instances, sender=self)
