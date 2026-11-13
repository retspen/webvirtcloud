"""A clone's VNC console gets a password of its own: one copied from its
source (a template's, say) would open the source's and every other clone's.
Its NIC filters keep no address of the source's."""

import unittest

from vrtManager.instance import wvmInstance


def clone_graphics(passwd_attribute):
    p = wvmInstance.__new__(wvmInstance)  # no connection: only these calls
    p.get_instances = lambda: []
    p._XMLDesc = lambda flags: f"""<domain><name>tpl</name><uuid>u</uuid><devices>
        <graphics type='vnc' port='-1' autoport='yes' {passwd_attribute} listen='0.0.0.0'/></devices></domain>"""
    tree, _ = p._clone_definition({"name": "copy"}, "abababab-0000-1111-2222-333333333333")
    return tree.find("devices/graphics")


class CloneConsoleTestCase(unittest.TestCase):
    def test_each_clone_gets_its_own_vnc_password(self):
        passwords = {clone_graphics("passwd='shared12'").get("passwd") for _ in range(5)}
        self.assertNotIn("shared12", passwords)
        self.assertEqual(len(passwords), 5)
        self.assertTrue(all(len(p) == 8 for p in passwords))  # the length VNC allows

    def test_a_source_without_a_password_gives_a_clone_with_one(self):
        self.assertEqual(len(clone_graphics("").get("passwd")), 8)

    def test_a_clones_nic_filter_has_its_mac_and_learns_its_ip(self):
        # the source's MAC and IP in clean-traffic's parameters would drop the clone's traffic
        p = wvmInstance.__new__(wvmInstance)
        p.get_instances = lambda: []
        p._XMLDesc = lambda flags: """<domain><name>tpl</name><uuid>u</uuid><devices>
            <interface type='network'><mac address='52:54:00:00:00:01'/><source network='default'/>
            <filterref filter='clean-traffic'><parameter name='MAC' value='52:54:00:00:00:01'/>
            <parameter name='IP' value='192.0.2.10'/><parameter name='CTRL_IP_LEARNING' value='dhcp'/></filterref>
            </interface></devices></domain>"""
        tree, _ = p._clone_definition({"name": "copy", "clone-net-mac-0": "52:54:00:00:00:02"},
                                      "abababab-0000-1111-2222-333333333333")
        parameters = {par.get("name"): par.get("value") for par in tree.findall("devices/interface/filterref/parameter")}
        self.assertEqual(parameters, {"MAC": "52:54:00:00:00:02", "CTRL_IP_LEARNING": "dhcp"})
        # without learning, the filter needs its IP: the clone keeps it, as it keeps IPV6
        p._XMLDesc = lambda flags: """<domain><name>tpl</name><uuid>u</uuid><devices>
            <interface type='network'><mac address='52:54:00:00:00:01'/><source network='default'/>
            <filterref filter='clean-traffic'><parameter name='IP' value='192.0.2.10'/>
            <parameter name='IPV6' value='2001:db8::10'/><parameter name='CTRL_IP_LEARNING' value='none'/></filterref>
            </interface></devices></domain>"""
        tree, _ = p._clone_definition({"name": "copy", "clone-net-mac-0": "52:54:00:00:00:02"},
                                      "abababab-0000-1111-2222-333333333333")
        self.assertEqual(tree.xpath("devices/interface/filterref/parameter/@name"), ["IP", "IPV6", "CTRL_IP_LEARNING"])
