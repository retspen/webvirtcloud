"""What the panel reads of the host's network filters and what it refuses
to change: which VMs use a filter, as they run and as saved; a filter in use
or referenced is not deleted; a create, clone or edit replaces no other
filter; references and rules as libvirt keeps them. libvirt's test driver has
no filters, so the connection is a mock."""

from unittest.mock import MagicMock

import libvirt
from django.test import SimpleTestCase
from lxml import etree
from vrtManager.nwfilters import wvmNWFilter, wvmNWFilters
from vrtManager.util import OperationError

UUID = "6d1f7a10-0000-4000-8000-00000000c0de"
WEB = (f"<filter name='web' chain='root'><uuid>{UUID}</uuid>"
       "<filterref filter='clean-traffic'><parameter name='IP' value='192.0.2.10'/>"
       "<parameter name='IP' value='192.0.2.11'/></filterref>"
       "<rule action='accept' direction='inout' priority='500'><arp match='no' arpsrcipaddr='192.0.2.1'/>"
       "<arp opcode='request'/></rule>"
       "<rule action='drop' direction='in'/></filter>")


def nwfilter(name, xml, uuid=UUID):
    return MagicMock(**{"name.return_value": name, "UUIDString.return_value": uuid, "XMLDesc.return_value": xml})


def vm(name, xml, saved=None, active=False, persistent=True):
    def describe(flags=0):
        return (saved or xml) if flags else xml
    return MagicMock(**{"name.return_value": name, "XMLDesc.side_effect": describe,
                        "isActive.return_value": active, "isPersistent.return_value": persistent})


def using(*names):
    refs = "".join(f"<interface type='network'><filterref filter='{name}'/></interface>" for name in names)
    return f"<domain><devices>{refs}</devices></domain>"


def error(code):
    err = libvirt.libvirtError("refused")
    err.get_error_code = lambda: code
    return err


def filters(*listed, domains=()):
    conn = wvmNWFilters.__new__(wvmNWFilters)
    conn.wvm = MagicMock(**{"listAllNWFilters.return_value": list(listed), "listAllDomains.return_value": list(domains),
                            "listNWFilters.return_value": [f.name() for f in listed]})
    return conn


def one(xml=WEB, names=("web", "clean-traffic", "no-spoofing")):
    conn = wvmNWFilter.__new__(wvmNWFilter)
    conn.nwfilter = nwfilter("web", xml)
    conn.wvm = MagicMock(**{"listNWFilters.return_value": list(names)})
    return conn


def defined(conn):
    return etree.fromstring(conn.wvm.nwfilterDefineXML.call_args.args[0])


class UsersTests(SimpleTestCase):
    def test_a_filter_is_used_as_the_vm_runs_and_as_saved(self):
        conn = filters(domains=[
            vm("stopped", using("a")),
            vm("running", using("b", "b"), saved=using("c"), active=True),  # c only from its next boot
            vm("transient", using("d"), saved=using("x"), active=True, persistent=False),
        ])
        self.assertEqual(conn.get_users(), {"a": ["stopped"], "b": ["running"], "c": ["running"], "d": ["transient"]})
        stopped, running, transient = conn.wvm.listAllDomains.return_value
        self.assertEqual((stopped.XMLDesc.call_count, running.XMLDesc.call_count, transient.XMLDesc.call_count), (2, 2, 1))

    def test_a_vm_gone_meanwhile_uses_nothing_other_errors_are_raised(self):
        gone = vm("gone", "")
        gone.XMLDesc.side_effect = error(libvirt.VIR_ERR_NO_DOMAIN)
        self.assertEqual(filters(domains=[gone, vm("web-1", using("a"))]).get_users(), {"a": ["web-1"]})
        gone.XMLDesc.side_effect = error(libvirt.VIR_ERR_OPERATION_FAILED)
        with self.assertRaises(libvirt.libvirtError):
            filters(domains=[gone]).get_users()


class DeleteTests(SimpleTestCase):
    def test_a_filter_a_vm_or_another_filter_uses_is_kept(self):
        target = nwfilter("clean-traffic", "<filter name='clean-traffic'/>", uuid="other")
        for conn, why in ((filters(target, domains=[vm("web-1", using("clean-traffic"))]), "used by VM web-1"),
                          (filters(target, nwfilter("web", WEB)), "referenced by filter web")):
            with self.subTest(why=why), self.assertRaisesRegex(OperationError, why):
                conn.delete_nwfilter("clean-traffic")
            conn.wvm.nwfilterLookupByName.return_value.undefine.assert_not_called()

    def test_an_unused_filter_is_undefined_libvirt_may_still_refuse(self):
        conn = filters(nwfilter("web", WEB))
        conn.delete_nwfilter("web")
        conn.wvm.nwfilterLookupByName.return_value.undefine.assert_called_once_with()
        conn.wvm.nwfilterLookupByName.return_value.undefine.side_effect = error(libvirt.VIR_ERR_OPERATION_INVALID)
        with self.assertRaises(libvirt.libvirtError):  # a VM started meanwhile: libvirt refuses itself
            conn.delete_nwfilter("web")


class IdentityTests(SimpleTestCase):
    def test_a_create_replaces_no_filter(self):
        conn = filters(nwfilter("web", WEB))
        for xml, why in ((WEB, "name already exists"),
                         (WEB.replace("name='web'", "name='other'"), "UUID already exists"),
                         ("<rule/>", "one <filter>"),
                         ("<filter name='a b'/>", "letters, digits"),
                         ('<!DOCTYPE filter [<!ENTITY n "web">]><filter name="&n;"/>', "DTD"),
                         ("", "not valid")):
            with self.subTest(why=why), self.assertRaisesRegex(OperationError, why):
                conn.create_nwfilter(xml)
        conn.wvm.nwfilterDefineXML.assert_not_called()
        conn.create_nwfilter("<filter name='other' chain='root'/>")
        conn.wvm.nwfilterDefineXML.assert_called_once_with("<filter name='other' chain='root'/>")

    def test_a_clone_keeps_rules_and_parameters_with_a_uuid_of_its_own(self):
        conn = filters(nwfilter("web", WEB))
        conn.wvm.nwfilterLookupByName.return_value.XMLDesc.return_value = WEB
        for name, why in (("web", "already exists"), ("web copy", "letters, digits"), ("", "letters, digits")):
            with self.subTest(name=name), self.assertRaisesRegex(OperationError, why):
                conn.clone_nwfilter("web", name)
        conn.clone_nwfilter("web", "web-copy")
        clone = defined(conn)
        self.assertEqual((clone.get("name"), clone.find("uuid")), ("web-copy", None))
        self.assertEqual(clone.xpath("filterref/parameter/@value"), ["192.0.2.10", "192.0.2.11"])
        self.assertEqual(len(clone.findall("rule")), 2)

    def test_an_edit_is_of_the_same_filter(self):
        conn = one()
        for xml, why in ((WEB.replace("name='web'", "name='other'"), "must define filter web"),
                         (WEB.replace(f"<uuid>{UUID}</uuid>", ""), "keep the filter's UUID"),
                         (WEB.replace(UUID, "11111111-2222-3333-4444-555555555555"), "keep the filter's UUID")):
            with self.subTest(why=why), self.assertRaisesRegex(OperationError, why):
                conn.edit(xml)
        conn.wvm.nwfilterDefineXML.assert_not_called()
        conn.edit(WEB.replace("priority='500'", "priority='400'"))
        conn.wvm.nwfilterDefineXML.assert_called_once()


class ChangeTests(SimpleTestCase):
    def test_a_reference_is_to_another_filter_of_the_host_not_yet_referenced(self):
        for name in ("web", "clean-traffic", "missing"):
            with self.subTest(name=name), self.assertRaisesRegex(OperationError, "cannot be referenced"):
                one().add_ref(name)
        conn = one()
        conn.add_ref("no-spoofing")
        self.assertEqual(defined(conn).xpath("filterref/@filter"), ["clean-traffic", "no-spoofing"])
        self.assertEqual(one().get_ref_choices(), ["no-spoofing"])

    def test_a_rule_is_one_rule_element(self):
        with self.assertRaisesRegex(OperationError, "one <rule>"):
            one().add_rule("<filter name='web'/>")

    def test_a_change_keeps_the_rest_of_the_filter(self):
        conn = one()
        conn.add_rule("<rule action='accept' direction='in'><udp dstportstart='53'/></rule>")
        tree = defined(conn)
        self.assertEqual((tree.findtext("uuid"), len(tree.findall("rule"))), (UUID, 3))
        self.assertEqual(tree.xpath("filterref/parameter/@value"), ["192.0.2.10", "192.0.2.11"])
        self.assertEqual(len(etree.fromstring(conn.get_xml()).findall("rule")), 2, "the page's own copy is not changed")


class ReadTests(SimpleTestCase):
    def test_rules_and_references_as_libvirt_keeps_them(self):
        conn = one()
        arp, drop = conn.get_rules()
        # two elements of one protocol, a match and a negated one; a rule of no protocol
        self.assertEqual([p["attributes"] for p in arp["protocols"]], [[("match", "no"), ("arpsrcipaddr", "192.0.2.1")],
                                                                      [("opcode", "request")]])
        self.assertEqual((drop["protocols"], drop["priority"]), ([], None))
        [ref] = conn.get_refs()
        self.assertEqual(ref["parameters"], [("IP", "192.0.2.10"), ("IP", "192.0.2.11")])
        self.assertEqual(conn.nwfilter.XMLDesc.call_count, 1)

    def test_the_list_reads_each_filter_once(self):
        conn = filters(nwfilter("web", WEB), nwfilter("clean-traffic", "<filter name='clean-traffic' chain='root'/>", "x"))
        info = conn.get_nwfilters_info()
        self.assertEqual([(f["name"], f["rules"], f["refs"]) for f in info],
                         [("clean-traffic", 0, []), ("web", 2, ["clean-traffic"])])
        for listed in conn.wvm.listAllNWFilters.return_value:
            self.assertEqual(listed.XMLDesc.call_count, 1)
