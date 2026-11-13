import posixpath
import re

from django import forms
from django.utils.translation import gettext_lazy as _

# pool target and source paths, both put into the pool XML: letters, digits,
# "/", "_", ".", ":" (/dev/disk/by-path names) and "-" not first and not right
# after "/". Written without nested repetition, which backtracked
# exponentially on crafted input.
POOL_PATH = re.compile(r"(?!-)(?:[/0-9a-zA-Z_.:]|(?<!/)-)+")
# the host's own directories: a pool there offers its files as volumes to
# delete, and a share mounted there hides them
SYSTEM_DIRS = ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc", "/root", "/run", "/sbin", "/sys", "/tmp",
               "/usr", "/var")
# inside /var, libvirt's directory holds images and ISOs beside these of its own
LIBVIRT_STATE = ("/var/lib/libvirt/dnsmasq", "/var/lib/libvirt/filesystems", "/var/lib/libvirt/lockd", "/var/lib/libvirt/lxc", "/var/lib/libvirt/network",
                 "/var/lib/libvirt/qemu", "/var/lib/libvirt/swtpm")
# directories whose subdirectories are a pool's place, not they themselves
PARENT_DIRS = ("/home", "/media", "/mnt", "/opt", "/srv")


def inside(path, other):
    return path == other or path.startswith(other.rstrip("/") + "/")


def system_dir(path):
    if path.startswith("/var/lib/libvirt/"):
        return any(inside(path, state) for state in LIBVIRT_STATE)
    return path == "/" or path in PARENT_DIRS or any(inside(path, system) for system in SYSTEM_DIRS)


class AddStgPool(forms.Form):
    """A new pool of the host. pools: the host's pools (get_storages_info),
    whose names and paths a new one may not take; ceph_secrets: the UUIDs of
    its Ceph secrets, the only ones an RBD pool can use."""

    # the fields each type needs, besides the name
    NEEDS = {
        "dir": ("target",),
        "logical": ("source", "erase_device"),
        "rbd": ("ceph_host", "ceph_pool", "ceph_user", "secret"),
        "netfs": ("netfs_host", "source", "target"),
    }

    name = forms.CharField(
        error_messages={"required": _("No pool name has been entered")}, max_length=20
    )
    stg_type = forms.ChoiceField(choices=[(t, t) for t in NEEDS])
    target = forms.CharField(label=_("Path"), max_length=100, required=False)
    source = forms.CharField(label=_("Device or remote path"), max_length=100, required=False)
    erase_device = forms.BooleanField(label=_("Erase the device"), required=False)
    ceph_user = forms.CharField(label=_("Ceph user"), required=False)
    ceph_host = forms.CharField(label=_("Ceph monitor"), required=False)
    ceph_pool = forms.CharField(label=_("Ceph pool"), required=False)
    secret = forms.CharField(label=_("Ceph secret"), required=False)
    netfs_host = forms.CharField(label=_("Server"), required=False)
    source_format = forms.ChoiceField(
        choices=[("auto", "auto"), ("nfs", "nfs"), ("glusterfs", "glusterfs"), ("cifs", "cifs")], required=False
    )

    def __init__(self, *args, pools=(), ceph_secrets=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.pools = pools
        self.ceph_secrets = ceph_secrets

    def clean_name(self):
        name = self.cleaned_data["name"]
        if not re.fullmatch("[a-zA-Z0-9._-]+", name) or name in (".", ".."):
            raise forms.ValidationError(
                _("The pool name must not contain any special characters")
            )
        if any(pool["name"] == name for pool in self.pools):
            raise forms.ValidationError(_("This host has a pool of that name"), code="taken")
        return name

    def clean_target(self):
        target = self.cleaned_data["target"]
        if not target:
            return target
        if not POOL_PATH.fullmatch(target):
            raise forms.ValidationError(
                _("The target must not contain any special characters")
            )
        target = posixpath.normpath(re.sub("/+", "/", target))  # "/srv/../etc/" is /etc
        if system_dir(target):
            raise forms.ValidationError(_("%(path)s is a system directory of the host") % {"path": target})
        # an RBD pool's path is its Ceph pool, not a directory
        for pool in self.pools:
            if pool["type"] == "rbd" or not pool["path"]:
                continue
            if pool["path"].rstrip("/") == target:
                raise forms.ValidationError(_("Pool %(pool)s uses this path") % {"pool": pool["name"]})
            # its volumes would be listed, and deleted, through both pools
            if inside(target, pool["path"]) or inside(pool["path"], target):
                raise forms.ValidationError(_("Pool %(pool)s uses %(path)s: one pool's directory cannot hold another's") % {
                    "pool": pool["name"], "path": pool["path"]})
        return target

    def clean_source(self):
        source = self.cleaned_data["source"]
        if source and not POOL_PATH.fullmatch(source):
            raise forms.ValidationError(
                _("The disk source must not contain any special characters")
            )
        return source

    def clean(self):
        data = super().clean()
        for field in self.NEEDS.get(data.get("stg_type"), ()):
            if not data.get(field) and field not in self.errors:
                self.add_error(field, _("This field is required."))
        if data.get("stg_type") == "rbd" and data.get("secret") and data["secret"] not in self.ceph_secrets:
            self.add_error("secret", _("Choose one of the host's Ceph secrets"))
        return data


class CreateVolumeForm(forms.Form):
    name = forms.CharField(max_length=120, help_text=_("Letters, digits, dot, dash and underscore."))
    format = forms.ChoiceField(
        required=True,
        choices=(("qcow2", "qcow2 (recommended)"), ("qcow", "qcow"), ("raw", "raw")),
    )
    size = forms.IntegerField(label=_("Size (GiB)"), min_value=1)
    meta_prealloc = forms.BooleanField(label=_("Preallocate metadata (qcow2)"), required=False)

    def clean_name(self):
        name = self.cleaned_data["name"]
        have_symbol = re.match("^[a-zA-Z0-9._-]+$", name)
        if not have_symbol:
            raise forms.ValidationError(
                _("The image name must not contain any special characters")
            )
        return name


class CloneImage(forms.Form):
    name = forms.CharField(max_length=120)
    image = forms.CharField(max_length=120)
    convert = forms.BooleanField(required=False)
    format = forms.ChoiceField(
        required=False,
        choices=(("qcow2", "qcow2 (recommended)"), ("qcow", "qcow"), ("raw", "raw")),
    )
    meta_prealloc = forms.BooleanField(label=_("Preallocate metadata (qcow2)"), required=False)

    def clean_name(self):
        name = self.cleaned_data["name"]
        have_symbol = re.match("^[a-zA-Z0-9._-]+$", name)
        if not have_symbol:
            raise forms.ValidationError(
                _("The image name must not contain any special characters")
            )
        elif len(name) > 120:
            raise forms.ValidationError(
                _("The image name must not exceed 120 characters")
            )
        return name
