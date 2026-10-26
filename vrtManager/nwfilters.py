from xml.etree import ElementTree

from vrtManager.connection import wvmConnect


class wvmNWFilters(wvmConnect):
    def get_nwfilter_info(self, name):
        nwfilter = self.get_nwfilter(name)
        xml = nwfilter.XMLDesc(0)
        uuid = nwfilter.UUIDString()
        return {"name": name, "uuid": uuid, "xml": xml}

    def create_nwfilter(self, xml):
        self.wvm.nwfilterDefineXML(xml)

    def clone_nwfilter(self, name, cln_name):
        nwfilter = self.get_nwfilter(name)
        if nwfilter:
            tree = ElementTree.fromstring(nwfilter.XMLDesc(0))
            tree.set("name", cln_name)
            uuid = tree.find("uuid")
            tree.remove(uuid)
            self.create_nwfilter(ElementTree.tostring(tree).decode())


class wvmNWFilter(wvmConnect):
    def __init__(self, host, login, passwd, conn, nwfiltername):
        wvmConnect.__init__(self, host, login, passwd, conn)
        self.nwfilter = self.get_nwfilter(nwfiltername)

    def _XMLDesc(self, flags):
        return self.nwfilter.XMLDesc(flags)

    def get_uuid(self):
        return self.nwfilter.UUIDString()

    def get_name(self):
        return self.nwfilter.name()

    def get_xml(self):
        """With the UUID: defined again with it, libvirt changes the filter in
        place, also while a VM uses it. It refuses XML it cannot parse or
        apply to the running VMs' interfaces."""
        return self._XMLDesc(0)

    def get_filter_refs(self):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        return [ref.get("filter") for ref in tree.findall("./filterref")]

    def get_rules(self):
        rules = []

        tree = ElementTree.fromstring(self._XMLDesc(0))
        for index, r in enumerate(tree.findall("./rule")):
            rule_action = r.get("action")
            rule_direction = r.get("direction")
            rule_priority = r.get("priority")
            rule_statematch = r.get("statematch")

            rule_directives = r.find("./")
            if rule_directives is not None:
                rule_directives = ElementTree.tostring(rule_directives).decode()

            rule_info = {
                "index": index,
                "action": rule_action,
                "direction": rule_direction,
                "priority": rule_priority,
                "statematch": rule_statematch,
                "directives": rule_directives,
            }

            rules.append(rule_info)

        return rules

    def delete_ref(self, name):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        for ref in tree.findall("./filterref"):
            if name == ref.get("filter"):
                tree.remove(ref)
                break
        return ElementTree.tostring(tree).decode()

    def delete_rule(self, index, action, direction, priority):
        """The filter without its rule at index (several rules may share
        action, direction and priority); those must still match, so a filter
        changed since the page was read loses no other rule."""
        tree = ElementTree.fromstring(self._XMLDesc(0))
        rules = tree.findall("./rule")
        if index >= len(rules) or (rules[index].get("action"), rules[index].get("direction"),
                                   rules[index].get("priority")) != (action, direction, priority):
            raise ValueError("The filter has changed; reload the page and try again")
        tree.remove(rules[index])
        return ElementTree.tostring(tree).decode()

    def add_ref(self, name):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        element = ElementTree.Element("filterref")
        element.attrib["filter"] = name
        tree.append(element)
        return ElementTree.tostring(tree).decode()

    def add_rule(self, xml):
        """The filter with the rule added as entered; libvirt keeps one
        protocol per rule, so it is never merged into another rule."""
        tree = ElementTree.fromstring(self._XMLDesc(0))
        rule = ElementTree.fromstring(xml)
        if rule.tag != "rule":
            raise ValueError("Enter one <rule> element")
        tree.append(rule)
        return ElementTree.tostring(tree).decode()
