"""A running VM's addresses come from the guest agent when it answers and
from the host's ARP table, so a VM without an agent shows its IPv4 address.
The agent is asked with a timeout: interfaceAddresses() would wait for a
hung agent indefinitely, and the VM page with it."""

import json
import unittest
from unittest.mock import MagicMock, patch

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from libvirt import VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP, libvirtError
from vrtManager import instance as module
from vrtManager.instance import wvmInstance

MAC = "52:54:00:00:00:01"
ARP = {"vnet0": {"hwaddr": MAC, "addrs": [{"type": 0, "addr": "192.0.2.10", "prefix": 0}]}}
# guest-network-get-interfaces: the loopback has no hardware address
AGENT = [{"name": "lo", "ip-addresses": [{"ip-address-type": "ipv4", "ip-address": "127.0.0.1", "prefix": 8}]},
         {"name": "eth0", "hardware-address": MAC, "ip-addresses": [
             {"ip-address-type": "ipv4", "ip-address": "192.0.2.20", "prefix": 24},
             {"ip-address-type": "ipv6", "ip-address": "2001:db8::20", "prefix": 64}]}]


def vm(agent):
    inst = wvmInstance.__new__(wvmInstance)
    inst._ip_cache = None
    inst.instance = MagicMock()
    inst.instance.interfaceAddresses.side_effect = lambda source: {VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP: ARP}[source]
    patch.object(inst, "get_status", return_value=1).start()
    patch.object(inst, "is_agent_ready", return_value=agent).start()
    return inst


class InterfaceAddressesTestCase(unittest.TestCase):
    def setUp(self):
        self.agent = patch.object(module, "qemuAgentCommand", return_value=json.dumps({"return": AGENT})).start()

    def tearDown(self):
        patch.stopall()

    def test_a_vm_without_an_agent_shows_its_arp_address(self):
        inst = vm(agent=False)
        self.assertEqual(inst.get_interface_addresses(MAC), (["192.0.2.10"], []))
        self.agent.assert_not_called()

    def test_the_agents_address_comes_first_and_is_asked_with_a_timeout(self):
        inst = vm(agent=True)
        self.assertEqual(inst.get_interface_addresses(MAC), (["192.0.2.20"], ["2001:db8::20/64"]))
        self.agent.assert_called_once_with(inst.instance, '{"execute": "guest-network-get-interfaces"}', 10, 0)
        self.assertEqual([c.args for c in inst.instance.interfaceAddresses.call_args_list],
                         [(VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP,)])

    def test_an_agent_that_does_not_answer_leaves_the_arp_address(self):
        self.agent.side_effect = libvirtError("guest agent didn't respond to command within '10' seconds")
        self.assertEqual(vm(agent=True).get_interface_addresses(MAC), (["192.0.2.10"], []))


class OsInfoTestCase(unittest.TestCase):
    def test_the_os_details_are_asked_with_a_timeout(self):
        answers = {"guest-get-osinfo": {"kernel-release": "6.12"}, "guest-get-timezone": {"zone": "UTC"},
                   "guest-get-host-name": {"host-name": "web"}}
        inst = wvmInstance.__new__(wvmInstance)
        inst.instance = MagicMock()
        with patch.object(module, "qemuAgentCommand",
                          side_effect=lambda dom, cmd, timeout, flags: json.dumps(
                              {"return": answers[json.loads(cmd)["execute"]]})) as agent:
            self.assertEqual(inst.osinfo(), {"kernel-release": "6.12", "zone": "UTC", "host-name": "web"})
        self.assertEqual({c.args[2] for c in agent.call_args_list}, {10})


if __name__ == "__main__":
    unittest.main()
