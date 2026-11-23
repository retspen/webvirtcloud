# LDAP

An LDAP user is authenticated by LDAP and authorized through the WebVirtCloud permissions. This is a minimal config; see the [django-auth-ldap documentation](https://django-auth-ldap.readthedocs.io) for more.

## Install the packages

The Docker image includes them. On an installer or manual installation, add them to the virtualenv; pip builds `python-ldap` against these headers. Install the headers for your system, then the packages:

```bash
apt-get -y install libldap2-dev libsasl2-dev   # Ubuntu / Debian
dnf -y install openldap-devel cyrus-sasl-devel   # RHEL / Rocky / AlmaLinux
zypper --non-interactive install -y openldap2-devel cyrus-sasl-devel   # openSUSE
```

```bash
/srv/webvirtcloud/venv/bin/pip3 install -r /srv/webvirtcloud/conf/requirements-ldap.txt
```

## Configure

Put one of the two examples below into [`data/local_settings.py`](configuration.md#local-settings), which has `ldap`, `LDAPSearch` and `NestedActiveDirectoryGroupType` at hand, and change the names to yours. In each:

- `AUTH_LDAP_REQUIRE_GROUP` is the group a user needs to sign in (`False`: no group needed);
- `AUTH_LDAP_USER_FLAGS_BY_GROUP` makes members of these groups staff or superusers;
- `AUTH_LDAP_USER_ATTR_MAP` fills the user's name and e-mail from LDAP.

### Active Directory

```python
AUTHENTICATION_BACKENDS.append("django_auth_ldap.backend.LDAPBackend")

AUTH_LDAP_SERVER_URI = "ldap://example.com"
AUTH_LDAP_BIND_DN = "username@example.com"
AUTH_LDAP_BIND_PASSWORD = "password"

AUTH_LDAP_USER_SEARCH = LDAPSearch(
    "CN=Users,DC=example,DC=com", ldap.SCOPE_SUBTREE, "(sAMAccountName=%(user)s)"
)
AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
    "CN=Users,DC=example,DC=com", ldap.SCOPE_SUBTREE, "(objectClass=group)"
)
AUTH_LDAP_GROUP_TYPE = NestedActiveDirectoryGroupType()

AUTH_LDAP_REQUIRE_GROUP = "CN=WebVirtCloud Access,CN=Users,DC=example,DC=com"
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

### OpenLDAP

```python
from django_auth_ldap.config import GroupOfUniqueNamesType

AUTHENTICATION_BACKENDS.append("django_auth_ldap.backend.LDAPBackend")

AUTH_LDAP_SERVER_URI = "ldap://example.com"
AUTH_LDAP_BIND_DN = "cn=username,ou=users,dc=example,dc=com"
AUTH_LDAP_BIND_PASSWORD = "password"

AUTH_LDAP_USER_SEARCH = LDAPSearch(
    "ou=users,dc=example,dc=com", ldap.SCOPE_SUBTREE, "(uid=%(user)s)"
)
AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
    "ou=groups,dc=example,dc=com", ldap.SCOPE_SUBTREE, "(objectClass=groupOfUniqueNames)"
)
AUTH_LDAP_GROUP_TYPE = GroupOfUniqueNamesType()

AUTH_LDAP_REQUIRE_GROUP = "cn=webvirtcloud-access,ou=groups,dc=example,dc=com"
AUTH_LDAP_USER_FLAGS_BY_GROUP = {
    "is_staff": "cn=webvirtcloud-staff,ou=groups,dc=example,dc=com",
    "is_superuser": "cn=webvirtcloud-admins,ou=groups,dc=example,dc=com",
}
AUTH_LDAP_USER_ATTR_MAP = {
    "first_name": "givenName",
    "last_name": "sn",
    "email": "mail",
}
```

Restart the panel as [Local settings](configuration.md#local-settings) says.

## Moving a user off LDAP

To move a user from LDAP to WebVirtCloud, change its password in the UI and remove it from the LDAP group.
