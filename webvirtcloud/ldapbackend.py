from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from ldap3 import Server, Connection, ALL
from django.conf import settings
from accounts.models import UserAttributes, UserInstance, UserSSHKey
from django.contrib.auth.models import Permission
from logs.models import Logs
import uuid
import logging

#/srv/webvirtcloud/ldap/ldapbackend.py
class LdapAuthenticationBackend(ModelBackend):
     
     def get_LDAP_user(self, username, password, filterString):
         logger.error("get_LDAP_user")
         try:
             server = Server(settings.LDAP_URL, port=settings.LDAP_PORT,use_ssl=settings.USE_SSL,get_info=ALL)
             connection = Connection(server,settings.LDAP_MASTER_DN, settings.LDAP_MASTER_PW, auto_bind=True)

             connection.search(settings.LDAP_ROOT_DN, '(&({attr}={login})({filter}))'.format(attr=settings.LDAP_USER_UID_PREFIX, login=username,filter=filterString), attributes=[settings.LDAP_USER_UID_PREFIX])

             if len(connection.response) == 0:
                 return None

             return connection.response[0]
         except:
             return None

    def authenticate(self, request, username=None, password=None, **kwargs):
        logger.error("authenticate")
        # Get the user information from the LDAP if he can be authenticated
        isAdmin = False
        isStaff = False
        if ldapAdmin 
        if get_LDAP_user(username, password, settings.LDAP_SEARCH_GROUP_FILTER_ADMINS) is None:
             if get_LDAP_user(username, password, settings.LDAP_SEARCH_GROUP_FILTER_STAFF) is None:
                  if get_LDAP_user(username, password, settings.LDAP_SEARCH_GROUP_FILTER_USERS) is None:
                      return None
             else
                  isStaff = True
        else
             isAdmin = True
             isStaff = True

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            user = User(username=username)
            user.is_staff = isStaff
            user.is_superuser = isAdmin
            user.password = uuid.uuid4().hex
            UserAttributes.objects.create(
                 user=user,
                 max_instances=1,
                 max_cpus=1,
                 max_memory=2048,
                 max_disk_size=20,
            )
            permission = Permission.objects.get(codename='clone_instances')
            user.user_permissions.add(permission)       
            user.save()
        return user

    def get_user(self, user_id):
        logger.error("get_user")
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None