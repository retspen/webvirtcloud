"""Deleting a host interface: a stopped one only; netcf removes a bridge's
members with the bridge, so they are defined again on their own (as virsh
iface-unbridge), all in one change of the host's configuration, rolled back
on a failure; a bridge with addresses and several members is refused."""

from unittest.mock import MagicMock

import libvirt
from django.test import SimpleTestCase
from lxml import etree
from vrtManager.interface import wvmInterface
from vrtManager.util import OperationError

ADDRESS = "<protocol family='ipv4'><ip address='192.0.2.10' prefix='24'/></protocol>"
BOND = "<interface type='bond' name='bond0'><bond mode='active-backup'><interface type='ethernet' name='eth1'/></bond></interface>"


def interface(xml, active=False):
    conn = wvmInterface.__new__(wvmInterface)
    conn.iface = MagicMock(**{"XMLDesc.return_value": xml, "isActive.return_value": active, "name.return_value": "br1"})
    conn.wvm = MagicMock()
    return conn


def delete(xml):
    conn = interface(xml)
    conn.delete_iface()
    conn.iface.undefine.assert_called_once_with()
    conn.wvm.changeBegin.assert_called_once_with(0)
    conn.wvm.changeCommit.assert_called_once_with(0)
    return [etree.fromstring(call.args[0]) for call in conn.wvm.interfaceDefineXML.call_args_list]


class DeleteInterfaceTestCase(SimpleTestCase):
    def test_the_only_member_takes_the_bridge_start_mode_and_addresses(self):
        (bond,) = delete(f"<interface type='bridge' name='br1'><start mode='onboot'/>{ADDRESS}<bridge>{BOND}</bridge></interface>")
        self.assertEqual(bond.get("name"), "bond0")
        self.assertEqual(bond.xpath("bond/@mode"), ["active-backup"])
        self.assertEqual(bond.xpath("bond/interface/@name"), ["eth1"])
        self.assertEqual(bond.xpath("start/@mode"), ["onboot"])
        self.assertEqual(bond.xpath("protocol/ip/@address"), ["192.0.2.10"])

    def test_several_members_take_the_start_mode(self):
        members = delete(
            "<interface type='bridge' name='br1'><start mode='onboot'/><bridge>"
            "<interface type='ethernet' name='eth1'/><interface type='ethernet' name='eth2'/></bridge></interface>"
        )
        self.assertEqual([m.get("name") for m in members], ["eth1", "eth2"])
        for member in members:
            self.assertEqual(member.xpath("start/@mode"), ["onboot"])
            self.assertEqual(member.xpath("protocol"), [])

    def test_a_bridge_with_addresses_and_several_members_is_refused(self):
        # which member would take the addresses is the user's choice
        conn = interface(f"<interface type='bridge' name='br1'>{ADDRESS}<bridge>"
                         "<interface type='ethernet' name='eth1'/><interface type='ethernet' name='eth2'/></bridge></interface>")
        with self.assertRaisesRegex(OperationError, "has addresses and several members"):
            conn.delete_iface()
        conn.iface.undefine.assert_not_called()

    def test_an_active_interface_is_refused(self):
        conn = interface("<interface type='ethernet' name='eth1'/>", active=True)
        with self.assertRaisesRegex(OperationError, "Stop interface br1 before deleting it"):
            conn.delete_iface()
        conn.iface.undefine.assert_not_called()

    def test_a_member_libvirt_refuses_rolls_the_whole_change_back(self):
        conn = interface(f"<interface type='bridge' name='br1'><bridge>{BOND}</bridge></interface>")
        conn.wvm.interfaceDefineXML.side_effect = libvirt.libvirtError("netcf: cannot write")
        with self.assertRaises(Exception):
            conn.delete_iface()
        conn.wvm.changeRollback.assert_called_once_with(0)
        conn.wvm.changeCommit.assert_not_called()

    def test_a_commit_libvirt_refuses_is_rolled_back(self):
        conn = interface("<interface type='ethernet' name='eth1'/>")
        conn.wvm.changeCommit.side_effect = libvirt.libvirtError("netcf: cannot commit")
        with self.assertRaises(Exception):
            conn.delete_iface()
        conn.wvm.changeRollback.assert_called_once_with(0)

    def test_an_interface_that_is_not_a_bridge_is_only_undefined(self):
        self.assertEqual(delete(f"<interface type='ethernet' name='eth1'><start mode='onboot'/>{ADDRESS}</interface>"), [])

    def test_a_rollback_that_fails_too_tells_both(self):
        conn = interface("<interface type='ethernet' name='eth1'/>")
        conn.wvm.changeCommit.side_effect = OperationError("netcf: cannot commit")
        conn.wvm.changeRollback.side_effect = OperationError("netcf: cannot roll back")
        with self.assertRaises(OperationError) as raised:
            conn.delete_iface()
        self.assertIn("netcf: cannot commit", str(raised.exception))
        self.assertIn("netcf: cannot roll back", str(raised.exception))
