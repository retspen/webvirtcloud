"""A clone's VNC console gets a password of its own: one copied from its
source (a template's, say) would open the source's and every other clone's."""

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
