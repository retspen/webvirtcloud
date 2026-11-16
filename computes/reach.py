"""Where the VMs of a bulk migration or a balance can migrate without a disk
copy, each host and each directory a pair of hosts may share asked once:
the pages ask it for every VM and destination."""

import os

from django.utils.translation import gettext_lazy as _
from libvirt import VIR_DOMAIN_XML_INACTIVE, libvirtError
from vrtManager.instance import file_disks, wvmInstances
from webvirtcloud.middleware import error_text


class Reach:
    def __init__(self, request):
        self.request = request
        self.conns = {}  # compute pk: its connection
        self.hosts = set()  # (source pk, target pk) a VM of the source was found able to go to
        self.shared = {}  # (source pk, target pk, directory): whether both hosts see it as one, or why not known
        self.directories = {}  # VM pk: the directories of its file disks, or the error that read them

    def _conn(self, compute):
        if compute.pk not in self.conns:
            self.conns[compute.pk] = wvmInstances(compute.hostname, compute.login, compute.password, compute.type)
        return self.conns[compute.pk]

    def refusal(self, instance, target):
        """Why the VM cannot migrate to target in a bulk migration, or None:
        target is another host the panel reaches, and both hosts see every
        disk file of the VM, now and at its next start (one they do not
        takes a copy, chosen on the VM's Migrate tab)."""
        from instances.jobs import migration_target

        pair = (instance.compute_id, target.pk)
        if pair not in self.hosts:
            # kept once it passed: a refusal may be the VM's own (gone meanwhile), not the hosts'
            try:
                migration_target(instance, target.pk)
                self.hosts.add(pair)
            except libvirtError as err:
                return error_text(self.request, err)
        if instance.pk not in self.directories:
            try:
                domain = instance.proxy.instance
                xmls = (domain.XMLDesc(0), domain.XMLDesc(VIR_DOMAIN_XML_INACTIVE))
                self.directories[instance.pk] = {os.path.dirname(path) for xml in xmls for _disk, path in file_disks(xml)}
            except libvirtError as err:
                self.directories[instance.pk] = error_text(self.request, err)
        if isinstance(self.directories[instance.pk], str):
            return self.directories[instance.pk]
        for directory in sorted(self.directories[instance.pk]):
            key = (*pair, directory)
            if key not in self.shared:
                try:
                    self.shared[key] = self._conn(target).shares(self._conn(instance.compute), directory)
                except libvirtError as err:  # a host's pools could not be read: not that destination
                    self.shared[key] = error_text(self.request, err)
            if isinstance(self.shared[key], str):
                return self.shared[key]
            if not self.shared[key]:
                return _("A disk file is not on storage both hosts share: migrate it from its page")
        return None
