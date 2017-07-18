from django.contrib.auth.backends import RemoteUserBackend
from accounts.models import UserInstance, UserAttributes
from instances.models import Instance

class MyRemoteUserBackend(RemoteUserBackend):

    #create_unknown_user = True

    def configure_user(self, user):
        #user.is_superuser = True
        UserAttributes.configure_user(user)
        return user

