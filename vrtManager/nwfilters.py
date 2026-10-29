import copy
import re
from functools import cached_property

from lxml import etree

from vrtManager import util
from vrtManager.connection import wvmConnect

# the names the panel gives filters: letters, digits, dots, dashes and underscores
NAME = re.compile(r"[A-Za-z0-9._-]+")


def element_text(element):
    """An element as the page shows it and sends it back: a rule or reference
    is changed only while it still reads the same."""
    return same_text(etree.tostring(element, encoding="unicode", with_tail=False))


def same_text(text):
    """text without the space between its tags, which a browser may send
    back with other line breaks."""
    return re.sub(r">\s+<", "><", text.strip())


def filter_info(nwfilter, tree):
    """What a filter and its XML tell: name, UUID, chain, priority, how many
    rules it has and the filters it references."""
    return {"name": nwfilter.name(), "uuid": nwfilter.UUIDString(), "chain": tree.get("chain"),
            "priority": tree.get("priority"), "rules": len(tree.findall("rule")),
            "refs": [ref.get("filter") for ref in tree.findall("filterref")]}


class wvmNWFilters(wvmConnect):
    def get_nwfilters_info(self):
        """Every filter of the host (filter_info), with the filters that
        reference it, by name: one listing, one XML read per filter."""
        filters = [filter_info(nwfilter, etree.fromstring(nwfilter.XMLDesc(0)))
                   for nwfilter in self.wvm.listAllNWFilters(0)]
        for nwfilter in filters:
            nwfilter["referenced_by"] = [other["name"] for other in filters if nwfilter["name"] in other["refs"]]
        return sorted(filters, key=lambda nwfilter: nwfilter["name"])

    def get_users(self):
        """The VMs whose interfaces reference each filter, by filter name, in
        any of their definitions (domain_trees)."""
        users = {}
        for vm, trees in self.domain_trees():
            names = set()
            for tree in trees:
                names.update(tree.xpath("devices/interface/filterref/@filter"))
            for name in names:
                users.setdefault(name, []).append(vm)
        return users

    def create_nwfilter(self, xml):
        """Define a filter from the XML entered: one whose name or UUID the
        host has is refused, as it would replace that filter."""
        tree = util.parse_xml(xml)
        if tree.tag != "filter":
            raise util.OperationError("Enter one <filter> element")
        if not NAME.fullmatch(tree.get("name") or ""):
            raise util.OperationError("The filter's name may have letters, digits, dots, dashes and underscores")
        for nwfilter in self.wvm.listAllNWFilters(0):
            if nwfilter.name() == tree.get("name"):
                raise util.OperationError("A network filter with this name already exists")
            if nwfilter.UUIDString() == tree.findtext("uuid"):
                raise util.OperationError("A network filter with this UUID already exists")
        self.wvm.nwfilterDefineXML(xml)

    def clone_nwfilter(self, name, clone_name):
        """Define a copy of filter name as clone_name, with its rules,
        references and their parameters, and a UUID of its own."""
        if not NAME.fullmatch(clone_name):
            raise util.OperationError("The filter's name may have letters, digits, dots, dashes and underscores")
        if clone_name in self.get_nwfilters():
            raise util.OperationError(f"A network filter named {clone_name} already exists")
        tree = etree.fromstring(self.get_nwfilter(name).XMLDesc(0))
        tree.set("name", clone_name)
        tree.remove(tree.find("uuid"))
        self.wvm.nwfilterDefineXML(etree.tostring(tree, encoding="unicode"))

    def delete_nwfilter(self, name):
        """Undefine a filter that no VM's interface and no other filter
        references. libvirt refuses only one a running VM uses; a stopped VM,
        or a VM using a filter that references it, would not start."""
        vms = self.get_users().get(name, [])
        if vms:
            raise util.OperationError(f"Filter {name} is used by VM {', '.join(vms)}")
        referencing = [nwfilter["name"] for nwfilter in self.get_nwfilters_info() if name in nwfilter["refs"]]
        if referencing:
            raise util.OperationError(f"Filter {name} is referenced by filter {', '.join(referencing)}")
        self.get_nwfilter(name).undefine()


class wvmNWFilter(wvmNWFilters):
    """A filter of the host. A page reads its XML once (tree); a change is
    the filter defined again with its UUID, which libvirt does in place, also
    while a VM uses it, and refuses for XML it cannot parse or apply to the
    running VMs' interfaces."""

    def __init__(self, host, login, passwd, conn, nwfiltername):
        wvmNWFilters.__init__(self, host, login, passwd, conn)
        self.nwfilter = self.get_nwfilter(nwfiltername)

    @cached_property
    def tree(self):
        return etree.fromstring(self.nwfilter.XMLDesc(0))

    def get_uuid(self):
        return self.nwfilter.UUIDString()

    def get_name(self):
        return self.nwfilter.name()

    def get_xml(self):
        return etree.tostring(self.tree, encoding="unicode")

    def get_refs(self):
        """The filters it references, each with its parameters in order (one
        name may repeat, giving a list) and its text."""
        return [{"filter": ref.get("filter"), "text": element_text(ref),
                 "parameters": [(param.get("name"), param.get("value")) for param in ref.findall("parameter")]}
                for ref in self.tree.findall("filterref")]

    def get_rules(self):
        """Its rules: action, direction, priority, statematch, each protocol
        element with its attributes (one rule may have several of one
        protocol, a match and a negated one) and the rule's text."""
        rules = []
        for rule in self.tree.findall("rule"):
            protocols = [{"name": protocol.tag, "attributes": list(protocol.attrib.items())} for protocol in rule]
            rules.append({"action": rule.get("action"), "direction": rule.get("direction"),
                          "priority": rule.get("priority"), "statematch": rule.get("statematch"),
                          "protocols": protocols, "text": element_text(rule)})
        return rules

    def get_ref_choices(self):
        """The filters a reference can be added to: not this one, nor one it
        references already."""
        taken = {self.get_name(), *(ref.get("filter") for ref in self.tree.findall("filterref"))}
        return [name for name in sorted(self.get_nwfilters()) if name not in taken]

    def _define(self, tree):
        self.wvm.nwfilterDefineXML(etree.tostring(tree, encoding="unicode"))

    def _without(self, tag, index, text):
        """The filter without its tag element at index, which must still read
        as text: a filter changed since the page was read loses nothing else.
        Returns the element removed."""
        tree = copy.deepcopy(self.tree)
        elements = tree.findall(tag)
        try:
            index = int(index)
        except ValueError:
            index = -1
        if not 0 <= index < len(elements) or element_text(elements[index]) != same_text(text):
            raise util.OperationError("The filter has changed; reload the page and try again")
        tree.remove(elements[index])
        self._define(tree)
        return elements[index]

    def edit(self, xml):
        """Define the filter anew from the XML entered: the same filter, of
        its name and UUID."""
        tree = util.parse_xml(xml)
        if tree.tag != "filter" or tree.get("name") != self.get_name():
            raise util.OperationError(f"The XML must define filter {self.get_name()}")
        if tree.findtext("uuid") != self.get_uuid():
            raise util.OperationError("The XML must keep the filter's UUID")
        self.wvm.nwfilterDefineXML(xml)

    def delete_rule(self, index, text):
        self._without("rule", index, text)

    def delete_ref(self, index, text):
        """Returns the name of the filter it referenced."""
        return self._without("filterref", index, text).get("filter")

    def add_ref(self, name):
        if name not in self.get_ref_choices():
            raise util.OperationError(f"Filter {name} cannot be referenced: it is this one, referenced already or not on the host")
        tree = copy.deepcopy(self.tree)
        etree.SubElement(tree, "filterref", filter=name)
        self._define(tree)

    def add_rule(self, xml):
        """The filter with the rule added as entered; libvirt keeps one
        protocol per rule, so it is never merged into another rule."""
        rule = util.parse_xml(xml)
        if rule.tag != "rule":
            raise util.OperationError("Enter one <rule> element")
        tree = copy.deepcopy(self.tree)
        tree.append(rule)
        self._define(tree)
