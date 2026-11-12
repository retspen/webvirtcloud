"""Test doubles for the computes tests."""

from unittest.mock import patch

from libvirt import libvirtError


def no_host_answers(test):
    """For test: the hosts a compute form or API call tries (Compute.clean)
    cannot be reached, so none is connected to, the machine's own libvirt
    least of all."""
    patcher = patch("computes.models.wvmHostDetails", side_effect=libvirtError("unreachable"))
    patcher.start()
    test.addCleanup(patcher.stop)


class Domain:
    """A libvirt domain as the VM list reads it: its name and UUID."""

    def __init__(self, name, uuid):
        self._name, self._uuid = name, uuid

    def name(self):
        return self._name

    def UUIDString(self):
        return self._uuid
