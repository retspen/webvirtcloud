from django.contrib.auth.backends import RemoteUserBackend
from accounts.models import UserInstance, UserAttributes
from instances.models import Instance

class MyRemoteUserBackend(RemoteUserBackend):

    #create_unknown_user = True
    default_instances = [ 'debian8-template' ]

    def create_missing_userattributes(self, user):
        try:
            userattributes = user.userattributes
        except UserAttributes.DoesNotExist:
            userattributes = UserAttributes(user=user)
            userattributes.save()

    def add_default_instances(self, user):
        existing_instances = UserInstance.objects.filter(user=user)
        if not existing_instances:
            for instance_name in self.default_instances:
                instance = Instance.objects.get(name=instance_name)
                user_instance = UserInstance(user=user, instance=instance)
                user_instance.save()

    def configure_user(self, user):
        #user.is_superuser = True
        self.create_missing_userattributes(user)
        self.add_default_instances(user)
        return user

