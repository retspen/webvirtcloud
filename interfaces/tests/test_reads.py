"""What the panel reads of the host's interfaces: each one's XML once, its
link as reported (an unknown speed is none), its members; which devices a new
bridge can take; how each family is addressed."""

from unittest.mock import MagicMock

import libvirt
from django.test import SimpleTestCase
from vrtManager.interface import wvmInterface, wvmInterfaces

BRIDGE = ("<interface type='bridge' name='br0'><mtu size='1500'/><link speed='4294967295' state='up'/>"
          "<mac address='52:54:00:aa:01:02'/><bridge stp='on' delay='0'>"
          "<interface type='ethernet' name='eno1'><link speed='1000' state='up'/><mac address='52:54:00:aa:01:03'/></interface>"
          "</bridge></interface>")
ETHERNET = "<interface type='ethernet' name='eno2'><link state='down'/><mac address='52:54:00:aa:01:04'/></interface>"


def iface(xml, active=1):
    name = xml.split("name='")[1].split("'")[0]
    mac = xml.split("mac address='")[1].split("'")[0]
    return MagicMock(**{"name.return_value": name, "MACString.return_value": mac, "XMLDesc.return_value": xml,
                        "isActive.return_value": active})


def error(code):
    err = libvirt.libvirtError("refused")
    err.get_error_code = lambda: code
    return err


class ReadTests(SimpleTestCase):
    def interfaces(self, *xmls, networks=()):
        conn = wvmInterfaces.__new__(wvmInterfaces)
        conn.wvm = MagicMock(**{"listAllInterfaces.return_value": [iface(x) for x in xmls],
                                "listAllNetworks.return_value": [MagicMock(**{"XMLDesc.return_value": n}) for n in networks]})
        return conn

    def test_each_interface_is_read_once(self):
        conn = self.interfaces(BRIDGE, ETHERNET)
        br0, eno2 = conn.get_ifaces_info()
        self.assertEqual((br0["type"], br0["link"], br0["speed"], br0["mtu"], br0["mac"]),
                         ("bridge", "up", None, "1500", "52:54:00:aa:01:02"))
        self.assertEqual(br0["members"], [{"name": "eno1", "type": "ethernet", "mac": "52:54:00:aa:01:03",
                                           "link": "up", "speed": "1000"}])
        self.assertEqual((eno2["link"], eno2["members"]), ("down", []))
        for listed in conn.wvm.listAllInterfaces.return_value:
            # name and MAC are held by libvirt's object: no call to the host
            self.assertEqual([c[0] for c in listed.mock_calls], ["XMLDesc", "name", "MACString", "isActive"])

    def test_an_interface_libvirt_cannot_write_is_read_as_saved(self):
        # netcf writes a link speed of -1 for a virtio card, then refuses that XML
        listed = iface(ETHERNET)
        listed.XMLDesc.side_effect = lambda flags=0: ETHERNET if flags else (_ for _ in ()).throw(error(libvirt.VIR_ERR_XML_ERROR))
        conn = self.interfaces()
        conn.wvm.listAllInterfaces.return_value = [listed]
        (eno2,) = conn.get_ifaces_info()
        self.assertEqual(eno2["name"], "eno2")

    def test_a_bridge_takes_no_bridge_member_network_bridge_or_tap(self):
        # as configured: a member the running bridge does not have yet is taken too
        conn = self.interfaces(BRIDGE, ETHERNET, networks=["<network><bridge name='virbr0'/></network>"])
        self.assertEqual(conn.get_member_candidates(["br0", "eno1", "eno2", "lo", "virbr0", "vnet3", "macvtap0"]), ["eno2"])
        for listed in conn.wvm.listAllInterfaces.return_value:
            listed.XMLDesc.assert_called_with(libvirt.VIR_INTERFACE_XML_INACTIVE)

    def test_a_device_in_a_bond_of_a_bridge_is_taken(self):
        nested = ("<interface type='bridge' name='br1'><mac address='52:54:00:aa:01:05'/><bridge><interface type='bond' name='bond0'><bond>"
                  "<interface type='ethernet' name='eno3'/><interface type='ethernet' name='eno4'/></bond></interface>"
                  "</bridge></interface>")
        conn = self.interfaces(nested)
        self.assertEqual(conn.get_member_candidates(["br1", "bond0", "eno3", "eno4", "eno5"]), ["eno5"])

    def test_each_family_says_how_it_is_addressed(self):
        conn = wvmInterface.__new__(wvmInterface)
        saved = ("<interface type='ethernet' name='eth0'><start mode='onboot'/>"
                 "<protocol family='ipv4'><ip address='198.51.100.10' prefix='24'/></protocol>"
                 "<protocol family='ipv6'><autoconf/></protocol></interface>")
        running = ("<interface type='ethernet' name='eth0'><protocol family='ipv4'><ip address='198.51.100.10' prefix='24'/></protocol>"
                   "<protocol family='ipv6'><ip address='2001:db8::5' prefix='64'/><ip address='2001:db8::6' prefix='64'/></protocol></interface>")
        conn.iface = MagicMock(**{"name.return_value": "eth0", "MACString.return_value": "52:54:00:00:00:01",
                                  "XMLDesc.side_effect": lambda flags=0: saved if flags else running})
        info = conn.get_info()
        self.assertEqual(info["start_mode"], "onboot")
        self.assertEqual(info["ipv4"], {"method": "static", "addresses": ["198.51.100.10/24"]})
        self.assertEqual(info["ipv6"], {"method": "autoconf", "addresses": ["2001:db8::5/64", "2001:db8::6/64"]})
        self.assertEqual(conn.iface.XMLDesc.call_count, 2)  # the running and the saved definition, once each

    def test_an_address_without_a_prefix_is_shown_without_one(self):
        conn = wvmInterface.__new__(wvmInterface)
        xml = "<interface type='ethernet' name='eth0'><protocol family='ipv4'><ip address='192.0.2.10'/></protocol></interface>"
        conn.iface = MagicMock(**{"name.return_value": "eth0", "MACString.return_value": "", "XMLDesc.return_value": xml})
        self.assertEqual(conn.get_info()["ipv4"]["addresses"], ["192.0.2.10"])
