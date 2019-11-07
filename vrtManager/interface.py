from vrtManager.connection import wvmConnect
from vrtManager import util
from xml.etree import ElementTree
from libvirt import VIR_INTERFACE_XML_INACTIVE


class wvmInterfaces(wvmConnect):
    def get_iface_info(self, name):
        iface = self.get_iface(name)
        xml = iface.XMLDesc(0)
        mac = iface.MACString()
        itype = util.get_xml_path(xml, "/interface/@type")
        state = iface.isActive()
        return {'name': name, 'type': itype, 'state': state, 'mac': mac}

    def define_iface(self, xml, flag=0):
        self.wvm.interfaceDefineXML(xml, flag)

    def create_iface(self, name, itype, mode, netdev, ipv4_type, ipv4_addr, ipv4_gw,
                     ipv6_type, ipv6_addr, ipv6_gw, stp, delay):
        xml = """<interface type='%s' name='%s'>
                    <start mode='%s'/>""" % (itype, name, mode)
        if ipv4_type == 'dhcp':
            xml += """<protocol family='ipv4'>
                        <dhcp/>
                      </protocol>"""
        if ipv4_type == 'static':
            address, prefix = ipv4_addr.split('/')
            xml += """<protocol family='ipv4'>
                        <ip address='%s' prefix='%s'/>
                        <route gateway='%s'/>
                      </protocol>""" % (address, prefix, ipv4_gw)
        if ipv6_type == 'dhcp':
            xml += """<protocol family='ipv6'>
                        <dhcp/>
                      </protocol>"""
        if ipv6_type == 'static':
            address, prefix = ipv6_addr.split('/')
            xml += """<protocol family='ipv6'>
                        <ip address='%s' prefix='%s'/>
                        <route gateway='%s'/>
                      </protocol>""" % (address, prefix, ipv6_gw)
        if itype == 'bridge':
            xml += """<bridge stp='%s' delay='%s'>
                        <interface name='%s' type='ethernet'/>
                      </bridge>""" % (stp, delay, netdev)
        xml += """</interface>"""
        self.define_iface(xml)
        iface = self.get_iface(name)
        iface.create()


class wvmInterface(wvmConnect):
    def __init__(self, host, login, passwd, conn, iface):
        wvmConnect.__init__(self, host, login, passwd, conn)
        self.iface = self.get_iface(iface)

    def _XMLDesc(self, flags=0):
        return self.iface.XMLDesc(flags)

    def get_start_mode(self):
        try:
            xml = self._XMLDesc(VIR_INTERFACE_XML_INACTIVE)
            return util.get_xml_path(xml, "/interface/start/@mode")
        except:
            return None

    def is_active(self):
        return self.iface.isActive()

    def get_mac(self):
        mac = self.iface.MACString()
        if mac:
            return mac
        else:
            return None

    def get_type(self):
        xml = self._XMLDesc()
        return util.get_xml_path(xml, "/interface/@type")

    def get_ipv4_type(self):
        try:
            xml = self._XMLDesc(VIR_INTERFACE_XML_INACTIVE)
            ipaddr = util.get_xml_path(xml, "/interface/protocol[@family='ipv4']/ip/@address")
            if ipaddr:
                return 'static'
            else:
                return 'dhcp'
        except:
            return None

    def get_ipv4(self):
        xml = self._XMLDesc()
        int_ipv4_ip = util.get_xml_path(xml, "/interface/protocol[@family='ipv4']/ip/@address")
        int_ipv4_mask = util.get_xml_path(xml, "/interface/protocol[@family='ipv4']/ip/@prefix")
        if not int_ipv4_ip or not int_ipv4_mask:
            return None
        else:
            return int_ipv4_ip + '/' + int_ipv4_mask

    def get_ipv6_type(self):
        try:
            xml = self._XMLDesc(VIR_INTERFACE_XML_INACTIVE)
            ipaddr = util.get_xml_path(xml, "/interface/protocol[@family='ipv6']/ip/@address")
            if ipaddr:
                return 'static'
            else:
                return 'dhcp'
        except:
            return None

    def get_ipv6(self):
        xml = self._XMLDesc()
        int_ipv6_ip = util.get_xml_path(xml, "/interface/protocol[@family='ipv6']/ip/@address")
        int_ipv6_mask = util.get_xml_path(xml, "/interface/protocol[@family='ipv6']/ip/@prefix")
        if not int_ipv6_ip or not int_ipv6_mask:
            return None
        else:
            return int_ipv6_ip + '/' + int_ipv6_mask

    def get_bridge(self):
        bridge = None
        if self.get_type() == 'bridge':
            bridge = util.get_xml_path(self._XMLDesc(), "/interface/bridge/interface/@name")
            for iface in self.get_bridge_slave_ifaces():
                if iface.get('state') == 'up' and iface.get('speed') is not 'unknown':
                    bridge = iface.get('name')
                    return bridge
            return bridge
        else:
            return None

    def get_bridge_slave_ifaces(self):
        ifaces = list()
        if self.get_type() == 'bridge':
            tree = ElementTree.fromstring(self._XMLDesc())
            for iface in tree.findall("./bridge/"):
                address = state = speed = None
                name = iface.get('name')
                type = iface.get('type')
                link = iface.find('link')
                if link is not None:
                    state = link.get('state')
                    speed = link.get('speed')
                mac = iface.find('mac')
                if mac is not None:
                    address = mac.get('address')
                ifaces.append({'name': name, 'type': type, 'state': state, 'speed': speed, 'mac': address})
            return ifaces
        else:
            return None

    def stop_iface(self):
        self.iface.destroy()

    def start_iface(self):
        self.iface.create()

    def delete_iface(self):
        self.iface.undefine()
