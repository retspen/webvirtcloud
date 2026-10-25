"""A running guest's root password and SSH keys through its QEMU guest
agent: the password as a crypt(3) hash, the key added to those it has. Each
is one agent command with a timeout: libvirt's own calls for them would wait
for a hung agent indefinitely, and setting the domain's agent timeout would
change it for every other agent call too."""

import base64
import json
import unittest
from unittest.mock import MagicMock, patch

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from libvirt import libvirtError
from vrtManager import instance as module
from vrtManager.instance import wvmInstance


class AgentAccessTestCase(unittest.TestCase):
    def setUp(self):
        self.vm = wvmInstance.__new__(wvmInstance)  # no connection: only these calls
        self.vm.instance = MagicMock()
        patcher = patch.object(module, "qemuAgentCommand", return_value='{"return":{}}')
        self.agent = patcher.start()
        self.addCleanup(patcher.stop)

    def sent(self):
        (dom, command, timeout, flags), = [c.args for c in self.agent.call_args_list]
        self.assertIs(dom, self.vm.instance)
        self.assertEqual((timeout, flags), (10, 0))
        return json.loads(command)

    def test_the_password_goes_as_a_hash(self):
        self.vm.set_user_password("root", "$6$salt$hash")
        self.assertEqual(self.sent(), {"execute": "guest-set-user-password", "arguments": {
            "username": "root", "password": base64.b64encode(b"$6$salt$hash").decode(), "crypted": True}})

    def test_the_key_is_added_to_the_users_keys(self):
        self.vm.add_authorized_key("root", "ssh-ed25519 AAAA laptop")
        self.assertEqual(self.sent(), {"execute": "guest-ssh-add-authorized-keys", "arguments": {
            "username": "root", "keys": ["ssh-ed25519 AAAA laptop"], "reset": False}})

    def test_the_agents_error_is_passed_on(self):
        self.agent.side_effect = libvirtError("guest agent didn't respond to command within '10' seconds")
        with self.assertRaisesRegex(libvirtError, "within '10' seconds"):
            self.vm.set_user_password("root", "$6$salt$hash")
