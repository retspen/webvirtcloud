from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from ldap3 import Server, Connection, ALL
from django.conf import settings
from accounts.models import UserAttributes, UserInstance, UserSSHKey
from django.contrib.auth.models import Permission
from logs.models import Logs
import uuid

#/srv/webvirtcloud/ldap/ldapbackend.py
class LdapAuthenticationBackend(ModelBackend):
     
     def get_LDAP_user(self, username, password, filterString):
         print('get_LDAP_user')
         try:
             server = Server(settings.LDAP_URL, port=settings.LDAP_PORT,
                 use_ssl=settings.USE_SSL,get_info=ALL)
             connection = Connection(server,
                                     settings.LDAP_MASTER_DN,
                                     settings.LDAP_MASTER_PW, auto_bind=True)

             connection.search(settings.LDAP_ROOT_DN, 
                 '(&({attr}={login})({filter}))'.format(
                     attr=settings.LDAP_USER_UID_PREFIX, 
                     login=username,
                     filter=filterString), attributes=[settings.LDAP_USER_UID_PREFIX])

             if len(connection.response) == 0:
                 print('get_LDAP_user-no response')
                 return None

             return connection.response[0]
         except:
             print('get_LDAP_user-error')
             return None

     def authenticate(self, request, username=None, password=None, **kwargs):
        if not settings.LDAP_ENABLED:
             return None
        print("authenticate_ldap")
        # Get the user information from the LDAP if he can be authenticated
        isAdmin = False
        isStaff = False
        
        if self.get_LDAP_user(username, password, settings.LDAP_SEARCH_GROUP_FILTER_ADMINS) is None:
             print("authenticate-not admin")
             if self.get_LDAP_user(username, password, settings.LDAP_SEARCH_GROUP_FILTER_STAFF) is None:
                  print("authenticate-not staff")
                  if self.get_LDAP_user(username, password, settings.LDAP_SEARCH_GROUP_FILTER_USERS) is None:
                      print("authenticate-not user")
                      return None
                  else:
                      print("authenticate-user")
             else:
                  isStaff = True
                  print("authenticate-staff")
        else:
             isAdmin = True
             isStaff = True
             print("authenticate-admin")

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            print("authenticate-create new user")
            user = User(username=username)
            user.is_active = True
            user.is_staff = isStaff
            user.is_superuser = isAdmin
            user.set_password(uuid.uuid4().hex)
            user.save()
            maxInstances = 1
            maxCpus = 1
            maxMemory = 128
            maxDiskSize = 1
            if isStaff:
                maxMemory = 2048
                maxDiskSize = 20
                permission = Permission.objects.get(codename='clone_instances')
                user.user_permissions.add(permission)
            if isAdmin:
                maxInstances = -1
                maxCpus = -1
                maxMemory = -1
                maxDiskSize = -1
                permission = Permission.objects.get(codename='clone_instances')
                user.user_permissions.add(permission)
            user.save()
            UserAttributes.objects.create(
                 user=user,
                 max_instances=maxInstances,
                 max_cpus=maxCpus,
                 max_memory=maxMemory,
                 max_disk_size=maxDiskSize,
            )            
            user.save()
            
            print("authenticate-user created")
        return user

     def get_user(self, user_id):
        if not settings.LDAP_ENABLED:
             return None
        print("get_user_ldap")
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            print("get_user-user not found")
            return None