"""Test doubles for the computes tests."""


class Domain:
    """A libvirt domain as the VM list reads it: its name and UUID."""

    def __init__(self, name, uuid):
        self._name, self._uuid = name, uuid

    def name(self):
        return self._name

    def UUIDString(self):
        return self._uuid
