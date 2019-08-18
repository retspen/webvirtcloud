from vrtManager.connection import wvmConnect
from xml.etree import ElementTree


class wvmNWFilters(wvmConnect):
    def get_nwfilter_info(self, name):
        nwfilter = self.get_nwfilter(name)
        xml = nwfilter.XMLDesc(0)
        uuid = nwfilter.UUIDString()
        return {'name': name, 'uuid': uuid, 'xml': xml}

    def create_nwfilter(self, xml):
        self.wvm.nwfilterDefineXML(xml)

    def clone_nwfilter(self, name, cln_name):
        nwfilter = self.get_nwfilter(name)
        if nwfilter:
            tree = ElementTree.fromstring(nwfilter.XMLDesc(0))
            tree.set('name', cln_name)
            uuid = tree.find('uuid')
            tree.remove(uuid)
            self.create_nwfilter(ElementTree.tostring(tree))


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

    def delete(self):
        self.nwfilter.undefine()

    def get_xml(self):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        uuid = tree.find('uuid')
        tree.remove(uuid)
        return ElementTree.tostring(tree)

    def get_filter_refs(self):
        refs = []
        tree = ElementTree.fromstring(self._XMLDesc(0))
        for ref in tree.findall("./filterref"):
            refs.append(ref.get('filter'))
        return refs

    def get_rules(self):
        rules = []

        tree = ElementTree.fromstring(self._XMLDesc(0))
        for r in tree.findall("./rule"):
            rule_action = r.get('action')
            rule_direction = r.get('direction')
            rule_priority = r.get('priority')
            rule_statematch = r.get('statematch')

            rule_directives = r.find("./")
            if rule_directives is not None:
                rule_directives = ElementTree.tostring(rule_directives)

            rule_info = {
                "action": rule_action,
                "direction": rule_direction,
                "priority": rule_priority,
                "statematch": rule_statematch,
                "directives": rule_directives
            }

            rules.append(rule_info)

        return rules

    def delete_ref(self, name):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        for ref in tree.findall("./filterref"):
            if name == ref.get('filter'):
                tree.remove(ref)
                break
        return ElementTree.tostring(tree)

    def delete_rule(self, action, direction, priority):
        tree = ElementTree.fromstring(self._XMLDesc(0))

        rule_tree = tree.findall("./rule[@action='%s'][@direction='%s'][@priority='%s']" % (action, direction, priority))
        if rule_tree:
            tree.remove(rule_tree[0])

        return ElementTree.tostring(tree)

    def add_ref(self, name):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        element = ElementTree.Element("filterref")
        element.attrib['filter'] = name
        tree.append(element)
        return ElementTree.tostring(tree)

    def add_rule(self, xml):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        rule = ElementTree.fromstring(xml)

        rule_action = rule.get('action')
        rule_direction = rule.get('direction')
        rule_priority = rule.get('priority')
        rule_directives = rule.find("./")
        rule_tree = tree.findall("./rule[@action='%s'][@direction='%s'][@priority='%s']" % (rule_action, rule_direction, rule_priority))

        if rule_tree:
            rule_tree[0].append(rule_directives)
        else:
            element = ElementTree.Element("rule")
            element.attrib['action'] = rule_action
            element.attrib['direction'] = rule_direction
            element.attrib['priority'] = rule_priority
            element.append(rule_directives)
            tree.append(element)

        return ElementTree.tostring(tree)
