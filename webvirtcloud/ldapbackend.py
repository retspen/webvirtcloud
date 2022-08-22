from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User, Group
from django.conf import settings
from accounts.models import UserAttributes, UserInstance, UserSSHKey
from django.contrib.auth.models import Permission
from logs.models import Logs
import uuid

try:
    from ldap3 import Server, Connection, ALL
    #/srv/webvirtcloud/ldap/ldapbackend.py
    class LdapAuthenticationBackend(ModelBackend):
         
        def get_LDAP_user(self, username, password, filterString):
            print('get_LDAP_user {}'.format(username))
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
                        filter=filterString), attributes=['*'])

                if len(connection.response) == 0:
                    print('get_LDAP_user-no response')
                    return None
                specificUser = connection.response[0]
                userDn = str(specificUser.get('raw_dn'),'utf-8')
                userGivenName = connection.entries[0].givenName
                userSn = connection.entries[0].sn
                userMail = connection.entries[0].mail
                with Connection(server, userDn, password) as con:
                    return username, userGivenName, userSn, userMail
            except Exception as e:
                print("LDAP Exception: {}".format(e))
                return None
            return None
    
        def authenticate(self, request, username=None, password=None, **kwargs):
            if not settings.LDAP_ENABLED:
                return None
            print("authenticate_ldap")
            # Get the user information from the LDAP if he can be authenticated
            isAdmin = False
            isStaff = False
            isTechnician = False

            requeteLdap = self.get_LDAP_user(username, password, settings.LDAP_SEARCH_GROUP_FILTER_ADMINS)
            isAdmin = requeteLdap is not None
            isStaff = requeteLdap is not None

            if requeteLdap is None:
                requeteLdap = self.get_LDAP_user(username, password, settings.LDAP_SEARCH_GROUP_FILTER_STAFF)
                isStaff = requeteLdap is not None

            if requeteLdap is None:
                requeteLdap = self.get_LDAP_user(username, password, settings.LDAP_SEARCH_GROUP_FILTER_TECHNICIANS)
                isTechnician = requeteLdap is not None

            if requeteLdap is None:
                requeteLdap = self.get_LDAP_user(username, password, settings.LDAP_SEARCH_GROUP_FILTER_USERS)

            if requeteLdap is None:
                print("User does not belong to any search group. Check LDAP_SEARCH_GROUP_FILTER in settings.")
                return None

            techniciansGroup = Group.objects.get(name='Technicians')

            try:
                user = User.objects.get(username=username)
                attributes = UserAttributes.objects.get(user=user)
                user.is_staff = isStaff
                user.is_superuser = isAdmin
                if not isTechnician and user.groups.filter(name='Technicians').exists():
                    user.groups.remove(techniciansGroup)
                elif isTechnician and not user.groups.filter(name='Technicians').exists():
                    user.groups.add(techniciansGroup)
                else:
                    print("The user is already in the Technicians group")
                    user.save()
                # TODO VERIFY
            except User.DoesNotExist:
                print(f"authenticate-create new user: {username}")
                user = User(username=username)
                user.first_name = requeteLdap[1]
                user.last_name = requeteLdap[2]
                user.email = requeteLdap[3]
                user.is_active = True
                user.is_staff = isStaff
                user.is_superuser = isAdmin
                user.set_password(uuid.uuid4().hex)
                user.save()
                if isTechnician:
                    user.groups.add(techniciansGroup)
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
except:
    class LdapAuthenticationBackend(ModelBackend):
        def authenticate(self, request, username=None, password=None, **kwargs):
            return None
        def get_user(self, user_id):
            return None
