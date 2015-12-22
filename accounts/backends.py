from django.contrib.auth.backends import RemoteUserBackend

class MyRemoteUserBackend(RemoteUserBackend):
    def configure_user(self, user):
        user.is_superuser = True
        return user

