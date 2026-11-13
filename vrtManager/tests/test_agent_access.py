"""A running guest's root password and SSH keys through its QEMU guest
agent: the password as a crypt(3) hash, the key added to those it has. Each
is one agent command with a timeout: libvirt's own calls for them would wait
for a hung agent indefinitely, and setting the domain's agent timeout would
change it for every other agent call too."""

import base64
import json
import unittest
from unittest.mock import MagicMock, patch

from libvirt import libvirtError
from vrtManager import instance as module
from vrtManager.instance import wvmInstance


def coded(code, text):
    err = libvirtError(text)
    err.get_error_code = lambda: code
    return err


class AgentAccessTestCase(unittest.TestCase):
    def setUp(self):
        self.vm = wvmInstance.__new__(wvmInstance)  # no connection: only these calls
        self.vm.instance = MagicMock()
        patcher = patch.object(module, "qemuAgentCommand", return_value='{"return":{}}')
        self.agent = patcher.start()
        self.addCleanup(patcher.stop)

    def sent(self):
        # the guest's OS first, then the change
        calls = [c.args for c in self.agent.call_args_list]
        for dom, _, timeout, flags in calls:
            self.assertIs(dom, self.vm.instance)
            self.assertEqual((timeout, flags), (10, 0))
        osinfo, change = [json.loads(command) for _, command, _, _ in calls]
        self.assertEqual(osinfo, {"execute": "guest-get-osinfo"})
        return change

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

    def test_a_windows_guest_is_refused_in_words(self):
        # its agent has no root account to change and takes no hash or SSH key
        self.agent.return_value = '{"return":{"id":"mswindows","name":"Microsoft Windows"}}'
        for change in (lambda: self.vm.set_user_password("root", "$6$salt$hash"),
                       lambda: self.vm.add_authorized_key("root", "ssh-ed25519 AAAA laptop")):
            with self.assertRaisesRegex(module.util.OperationError, "runs Windows"):
                change()
        self.assertEqual([json.loads(c.args[1])["execute"] for c in self.agent.call_args_list],
                         ["guest-get-osinfo", "guest-get-osinfo"])

    def test_an_agent_without_osinfo_still_gets_the_change(self):
        # an agent that lacks guest-get-osinfo or has it disabled answers with an error
        def answer(dom, command, timeout, flags):
            if json.loads(command)["execute"] == "guest-get-osinfo":
                raise coded(module.VIR_ERR_AGENT_COMMAND_FAILED, "Command guest-get-osinfo has been disabled")
            return '{"return":{}}'

        self.agent.side_effect = answer
        self.vm.add_authorized_key("root", "ssh-ed25519 AAAA laptop")
        self.assertEqual(self.sent()["execute"], "guest-ssh-add-authorized-keys")

    def test_an_osinfo_that_times_out_says_nothing_was_changed(self):
        # not the timeout of the change, which the agent may still run
        self.agent.side_effect = coded(module.VIR_ERR_AGENT_COMMAND_TIMEOUT, "guest agent command timed out")
        with self.assertRaisesRegex(module.util.OperationError, "nothing was changed"):
            self.vm.set_user_password("root", "$6$salt$hash")
        self.assertEqual(self.agent.call_count, 1)


class ShutdownTestCase(unittest.TestCase):
    """Power off: libvirt waits 60 s for a hung agent before ACPI, so one that
    does not answer a ping is passed over."""

    def shutdown(self, state=1, ready=True, ping=None):
        vm = wvmInstance.__new__(wvmInstance)
        vm.instance = MagicMock()
        vm.instance.state.return_value = [state, 1]
        with patch.object(wvmInstance, "is_agent_ready", return_value=ready), \
                patch.object(module, "qemuAgentCommand", side_effect=ping, return_value='{"return":{}}') as agent:
            vm.shutdown()
        return vm.instance.shutdownFlags.call_args.args[0], agent.call_count

    def test_an_answering_agent_is_left_to_libvirt(self):
        self.assertEqual(self.shutdown(), (0, 1))

    def test_a_hung_agent_is_passed_over_for_acpi(self):
        hung = coded(module.VIR_ERR_AGENT_COMMAND_TIMEOUT, "guest agent didn't respond to command within '10' seconds")
        self.assertEqual(self.shutdown(ping=hung), (module.VIR_DOMAIN_SHUTDOWN_ACPI_POWER_BTN, 1))

    def test_an_agent_with_ping_disabled_is_left_to_libvirt(self):
        disabled = coded(module.VIR_ERR_AGENT_COMMAND_FAILED, "Command guest-ping has been disabled")
        self.assertEqual(self.shutdown(ping=disabled), (0, 1))

    def test_without_a_connected_agent_or_when_paused_there_is_no_ping(self):
        self.assertEqual(self.shutdown(ready=False), (0, 0))
        self.assertEqual(self.shutdown(state=3), (0, 0))
