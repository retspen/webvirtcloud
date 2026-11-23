# LDAP

The options below go into [`data/local_settings.py`](configuration.md#local-settings), which has `ldap`, `LDAPSearch` and `NestedActiveDirectoryGroupType` at hand. Variants for Active Directory and OpenLDAP are shown; this is a minimal config, see the [django-auth-ldap documentation](https://django-auth-ldap.readthedocs.io) for more.

The Docker image includes the LDAP packages. On an installer or manual install, add them to the virtualenv first; pip builds `python-ldap` against these headers:

```bash
apt-get -y install libldap2-dev libsasl2-dev   # Ubuntu / Debian
dnf -y install openldap-devel cyrus-sasl-devel   # RHEL / Rocky / AlmaLinux
zypper --non-interactive install -y openldap2-devel cyrus-sasl-devel   # openSUSE
/srv/webvirtcloud/venv/bin/pip3 install -r /srv/webvirtcloud/conf/requirements-ldap.txt
```

Enable the LDAP backend:

```python
AUTHENTICATION_BACKENDS.append("django_auth_ldap.backend.LDAPBackend")
```

Set the LDAP server and bind DN:

```python
# Active Directory
AUTH_LDAP_SERVER_URI = "ldap://example.com"
AUTH_LDAP_BIND_DN = "username@example.com"
AUTH_LDAP_BIND_PASSWORD = "password"

# OpenLDAP
AUTH_LDAP_SERVER_URI = "ldap://example.com"
AUTH_LDAP_BIND_DN = "cn=username,ou=users,dc=example,dc=com"
AUTH_LDAP_BIND_PASSWORD = "password"
```

Set the user and group search base and filter:

```python
# Active Directory
AUTH_LDAP_USER_SEARCH = LDAPSearch(
    "CN=Users,DC=example,DC=com", ldap.SCOPE_SUBTREE, "(sAMAccountName=%(user)s)"
)
AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
    "CN=Users,DC=example,DC=com", ldap.SCOPE_SUBTREE, "(objectClass=group)"
)
AUTH_LDAP_GROUP_TYPE = NestedActiveDirectoryGroupType()

# OpenLDAP
AUTH_LDAP_USER_SEARCH = LDAPSearch(
    "ou=users,dc=example,dc=com", ldap.SCOPE_SUBTREE, "(uid=%(user)s)"
)
AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
    "ou=groups,dc=example,dc=com", ldap.SCOPE_SUBTREE, "(objectClass=groupOfUniqueNames)"
)
from django_auth_ldap.config import GroupOfUniqueNamesType
AUTH_LDAP_GROUP_TYPE = GroupOfUniqueNamesType()
```

Set the group required to access WebVirtCloud (`False` disables this filter):

```python
AUTH_LDAP_REQUIRE_GROUP = "CN=WebVirtCloud Access,CN=Users,DC=example,DC=com"
```

Populate user fields from LDAP:

```python
AUTH_LDAP_USER_FLAGS_BY_GROUP = {
    "is_staff": "CN=WebVirtCloud Staff,CN=Users,DC=example,DC=com",
    "is_superuser": "CN=WebVirtCloud Admins,CN=Users,DC=example,DC=com",
}
AUTH_LDAP_USER_ATTR_MAP = {
    "first_name": "givenName",
    "last_name": "sn",
    "email": "mail",
}
```

An LDAP user is authenticated by LDAP and authorized through the WebVirtCloud permissions. To move a user from LDAP to WebVirtCloud, change its password in the UI and remove it from the LDAP group.
