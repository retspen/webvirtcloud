import time
import os.path
try:
    from libvirt import libvirtError, VIR_DOMAIN_XML_SECURE, VIR_MIGRATE_LIVE, VIR_MIGRATE_UNSAFE
except:
    from libvirt import libvirtError, VIR_DOMAIN_XML_SECURE, VIR_MIGRATE_LIVE
from vrtManager import util
from xml.etree import ElementTree
from datetime import datetime
from vrtManager.connection import wvmConnect
from vrtManager.storage import wvmStorage
from webvirtcloud.settings import QEMU_CONSOLE_TYPES
from webvirtcloud.settings import INSTANCE_VOLUME_DEFAULT_OWNER as owner


class wvmInstances(wvmConnect):
    def get_instance_status(self, name):
        inst = self.get_instance(name)
        return inst.info()[0]

    def get_instance_memory(self, name):
        inst = self.get_instance(name)
        mem = util.get_xml_path(inst.XMLDesc(0), "/domain/currentMemory")
        return int(mem) / 1024

    def get_instance_vcpu(self, name):
        inst = self.get_instance(name)
        cur_vcpu = util.get_xml_path(inst.XMLDesc(0), "/domain/vcpu/@current")
        if cur_vcpu:
            vcpu = cur_vcpu
        else:
            vcpu = util.get_xml_path(inst.XMLDesc(0), "/domain/vcpu")
        return vcpu

    def get_instance_managed_save_image(self, name):
        inst = self.get_instance(name)
        return inst.hasManagedSaveImage(0)

    def get_uuid(self, name):
        inst = self.get_instance(name)
        return inst.UUIDString()

    def start(self, name):
        dom = self.get_instance(name)
        dom.create()

    def shutdown(self, name):
        dom = self.get_instance(name)
        dom.shutdown()

    def force_shutdown(self, name):
        dom = self.get_instance(name)
        dom.destroy()

    def managedsave(self, name):
        dom = self.get_instance(name)
        dom.managedSave(0)

    def managed_save_remove(self, name):
        dom = self.get_instance(name)
        dom.managedSaveRemove(0)

    def suspend(self, name):
        dom = self.get_instance(name)
        dom.suspend()

    def resume(self, name):
        dom = self.get_instance(name)
        dom.resume()

    def moveto(self, conn, name, live, unsafe, undefine, offline):
        flags = 0
        if live and conn.get_status() == 1:
            flags |= VIR_MIGRATE_LIVE
        if unsafe and conn.get_status() == 1:
            flags |= VIR_MIGRATE_UNSAFE
        dom = conn.get_instance(name)
        xml = dom.XMLDesc(VIR_DOMAIN_XML_SECURE)
        if not offline:
            dom.migrate(self.wvm, flags, None, None, 0)
        if undefine:
            dom.undefine()
        self.wvm.defineXML(xml)

    def graphics_type(self, name):
        inst = self.get_instance(name)
        console_type = util.get_xml_path(inst.XMLDesc(0), "/domain/devices/graphics/@type")
        if console_type is None:
            return "None"
        return console_type

    def graphics_listen(self, name):
        inst = self.get_instance(name)
        listen_addr = util.get_xml_path(inst.XMLDesc(0), "/domain/devices/graphics/@listen")
        if listen_addr is None:
            listen_addr = util.get_xml_path(inst.XMLDesc(0), "/domain/devices/graphics/listen/@address")
            if listen_addr is None:
                    return "None"
        return listen_addr

    def graphics_port(self, name):
        inst = self.get_instance(name)
        console_port = util.get_xml_path(inst.XMLDesc(0), "/domain/devices/graphics/@port")
        if console_port is None:
            return "None"
        return console_port

    def domain_name(self, name):
        inst = self.get_instance(name)
        domname = util.get_xml_path(inst.XMLDesc(0), "/domain/name")
        if domname is None:
            return "NoName"
        return domname

    def graphics_passwd(self, name):
        inst = self.get_instance(name)
        password = util.get_xml_path(inst.XMLDesc(VIR_DOMAIN_XML_SECURE), "/domain/devices/graphics/@passwd")
        if password is None:
            return "None"
        return password


class wvmInstance(wvmConnect):
    def __init__(self, host, login, passwd, conn, vname):
        wvmConnect.__init__(self, host, login, passwd, conn)
        self.instance = self.get_instance(vname)

    def start(self):
        self.instance.create()

    def shutdown(self):
        self.instance.shutdown()

    def force_shutdown(self):
        self.instance.destroy()

    def managedsave(self):
        self.instance.managedSave(0)

    def managed_save_remove(self):
        self.instance.managedSaveRemove(0)

    def suspend(self):
        self.instance.suspend()

    def resume(self):
        self.instance.resume()

    def delete(self):
        self.instance.undefine()

    def _XMLDesc(self, flag):
        return self.instance.XMLDesc(flag)

    def _defineXML(self, xml):
        return self.wvm.defineXML(xml)

    def get_status(self):
        return self.instance.info()[0]

    def get_autostart(self):
        return self.instance.autostart()

    def set_autostart(self, flag):
        return self.instance.setAutostart(flag)

    def get_uuid(self):
        return self.instance.UUIDString()

    def get_vcpu(self):
        vcpu = util.get_xml_path(self._XMLDesc(0), "/domain/vcpu")
        return int(vcpu)

    def get_cur_vcpu(self):
        cur_vcpu = util.get_xml_path(self._XMLDesc(0), "/domain/vcpu/@current")
        if cur_vcpu:
            return int(cur_vcpu)

    def get_memory(self):
        mem = util.get_xml_path(self._XMLDesc(0), "/domain/memory")
        return int(mem) / 1024

    def get_cur_memory(self):
        mem = util.get_xml_path(self._XMLDesc(0), "/domain/currentMemory")
        return int(mem) / 1024

    def get_title(self):
        title = util.get_xml_path(self._XMLDesc(0), "/domain/title")
        return title if title else ''

    def get_filterrefs(self):

        def filterrefs(ctx):
            result = []
            for net in ctx.xpath('/domain/devices/interface'):
                filterref = net.xpath('filterref/@filter')
                if filterref:
                    result.append(filterref[0])
            return result

        return util.get_xml_path(self._XMLDesc(0), func=filterrefs)


    def get_description(self):
        description = util.get_xml_path(self._XMLDesc(0), "/domain/description")
        return description if description else ''

    def get_max_memory(self):
        return self.wvm.getInfo()[1] * 1048576

    def get_max_cpus(self):
        """Get number of physical CPUs."""
        hostinfo = self.wvm.getInfo()
        pcpus = hostinfo[4] * hostinfo[5] * hostinfo[6] * hostinfo[7]
        range_pcpus = xrange(1, int(pcpus + 1))
        return range_pcpus

    def get_net_device(self):
        def get_mac_ipaddr(net, mac_host):
            def fixed(doc):
                for net in doc.xpath('/network/ip/dhcp/host'):
                    mac = net.xpath('@mac')[0]
                    host = net.xpath('@ip')[0]
                    if mac == mac_host:
                        return host
                return None

            return util.get_xml_path(net.XMLDesc(0), func=fixed)

        def networks(ctx):
            result = []
            for net in ctx.xpath('/domain/devices/interface'):
                mac_host = net.xpath('mac/@address')[0]
                network_host = net.xpath('source/@network|source/@bridge|source/@dev')[0]
                target_host = '' if not net.xpath('target/@dev') else net.xpath('target/@dev')[0]
                filterref_host = '' if not net.xpath('filterref/@filter') else net.xpath('filterref/@filter')[0]
                try:
                    net = self.get_network(network_host)
                    ip = get_mac_ipaddr(net, mac_host)
                except libvirtError as e:
                    ip = None
                result.append({'mac': mac_host, 'nic': network_host, 'target': target_host,'ip': ip, 'filterref': filterref_host})
            return result

        return util.get_xml_path(self._XMLDesc(0), func=networks)

    def get_disk_devices(self):
        def disks(doc):
            result = []
            dev = None
            volume = None
            storage = None
            src_fl = None
            disk_format = None
            used_size = None
            disk_size = None
            
            for disk in doc.xpath('/domain/devices/disk'):
                device = disk.xpath('@device')[0]
                if device == 'disk':
                    try:
                        dev = disk.xpath('target/@dev')[0]
                        bus = disk.xpath('target/@bus')[0]
                        src_fl = disk.xpath('source/@file|source/@dev|source/@name|source/@volume')[0]
                        try:
                            disk_format = disk.xpath('driver/@type')[0]
                        except:
                            pass
                        try:
                            vol = self.get_volume_by_path(src_fl)
                            volume = vol.name()

                            disk_size = vol.info()[1]
                            used_size = vol.info()[2]
                            stg = vol.storagePoolLookupByVolume()
                            storage = stg.name()
                        except libvirtError:
                            volume = src_fl
                    except:
                        pass
                    finally:
                        result.append(
                            {'dev': dev, 'bus': bus, 'image': volume, 'storage': storage, 'path': src_fl,
                             'format': disk_format, 'size': disk_size, 'used': used_size})
            return result

        return util.get_xml_path(self._XMLDesc(0), func=disks)

    def get_media_devices(self):
        def disks(doc):
            result = []
            dev = None
            volume = None
            storage = None
            src_fl = None
            for media in doc.xpath('/domain/devices/disk'):
                device = media.xpath('@device')[0]
                if device == 'cdrom':
                    try:
                        dev = media.xpath('target/@dev')[0]
                        bus = media.xpath('target/@bus')[0]
                        try:
                            src_fl = media.xpath('source/@file')[0]
                            vol = self.get_volume_by_path(src_fl)
                            volume = vol.name()
                            stg = vol.storagePoolLookupByVolume()
                            storage = stg.name()
                        except:
                            src_fl = None
                            volume = src_fl
                    except:
                        pass
                    finally:
                        result.append({'dev': dev, 'image': volume, 'storage': storage, 'path': src_fl, 'bus': bus})
            return result

        return util.get_xml_path(self._XMLDesc(0), func=disks)

    def mount_iso(self, dev, image):
        def attach_iso(dev, disk, vol):
            if disk.get('device') == 'cdrom':
                for elm in disk:
                    if elm.tag == 'target':
                        if elm.get('dev') == dev:
                            src_media = ElementTree.Element('source')
                            src_media.set('file', vol.path())
                            disk.insert(2, src_media)
                            return True

        storages = self.get_storages(only_actives=True)
        for storage in storages:
            stg = self.get_storage(storage)
            if stg.info()[0] != 0:
                for img in stg.listVolumes():
                    if image == img:
                        vol = stg.storageVolLookupByName(image)
        tree = ElementTree.fromstring(self._XMLDesc(0))
        for disk in tree.findall('devices/disk'):
            if attach_iso(dev, disk, vol):
                break
        if self.get_status() == 1:
            xml = ElementTree.tostring(disk)
            self.instance.attachDevice(xml)
            xmldom = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        if self.get_status() == 5:
            xmldom = ElementTree.tostring(tree)
        self._defineXML(xmldom)

    def umount_iso(self, dev, image):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        for disk in tree.findall('devices/disk'):
            if disk.get('device') == 'cdrom':
                for elm in disk:
                    if elm.tag == 'source':
                        if elm.get('file') == image:
                            src_media = elm
                    if elm.tag == 'target':
                        if elm.get('dev') == dev:
                            disk.remove(src_media)
        if self.get_status() == 1:
            xml_disk = ElementTree.tostring(disk)
            self.instance.attachDevice(xml_disk)
            xmldom = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        if self.get_status() == 5:
            xmldom = ElementTree.tostring(tree)
        self._defineXML(xmldom)

    def attach_disk(self, source, target, sourcetype='file', device='disk', driver='qemu', subdriver='raw', cache='none', targetbus='ide'):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        xml_disk = """
        <disk type='%s' device='%s'>
          <driver name='%s' type='%s' cache='%s'/>
          <source file='%s'/>
          <target dev='%s' bus='%s'/>
        </disk>
        """ % (sourcetype, device, driver, subdriver, cache, source, target, targetbus)
        if self.get_status() == 5:
            devices = tree.find('devices')
            elm_disk = ElementTree.fromstring(xml_disk)
            devices.append(elm_disk)
            xmldom = ElementTree.tostring(tree)
            self._defineXML(xmldom)

    def detach_disk(self, dev):
        tree = ElementTree.fromstring(self._XMLDesc(0))

        for disk in tree.findall("./devices/disk"):
            target = disk.find("target")
            if target.get("dev") == dev:
                devices = tree.find('devices')
                devices.remove(disk)

                if self.get_status() == 1:
                    xml_disk = ElementTree.tostring(disk)
                    ret = self.instance.detachDevice(xml_disk)
                    xmldom = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
                if self.get_status() == 5:
                    xmldom = ElementTree.tostring(tree)
                break
        self._defineXML(xmldom)

    def cpu_usage(self):
        cpu_usage = {}
        if self.get_status() == 1:
            nbcore = self.wvm.getInfo()[2]
            cpu_use_ago = self.instance.info()[4]
            time.sleep(1)
            cpu_use_now = self.instance.info()[4]
            diff_usage = cpu_use_now - cpu_use_ago
            cpu_usage['cpu'] = 100 * diff_usage / (1 * nbcore * 10 ** 9L)
        else:
            cpu_usage['cpu'] = 0
        return cpu_usage

    def disk_usage(self):
        devices = []
        dev_usage = []
        tree = ElementTree.fromstring(self._XMLDesc(0))
        for disk in tree.findall('devices/disk'):
            if disk.get('device') == 'disk':
                dev_file = None
                dev_bus = None
                network_disk = True
                for elm in disk:
                    if elm.tag == 'source':
                        if elm.get('protocol'):
                            dev_file = elm.get('protocol')
                            network_disk = True
                        if elm.get('file'):
                            dev_file = elm.get('file')
                        if elm.get('dev'):
                            dev_file = elm.get('dev')
                    if elm.tag == 'target':
                        dev_bus = elm.get('dev')
                if (dev_file and dev_bus) is not None:
                    if network_disk:
                        dev_file = dev_bus
                    devices.append([dev_file, dev_bus])
        for dev in devices:
            if self.get_status() == 1:
                rd_use_ago = self.instance.blockStats(dev[0])[1]
                wr_use_ago = self.instance.blockStats(dev[0])[3]
                time.sleep(1)
                rd_use_now = self.instance.blockStats(dev[0])[1]
                wr_use_now = self.instance.blockStats(dev[0])[3]
                rd_diff_usage = rd_use_now - rd_use_ago
                wr_diff_usage = wr_use_now - wr_use_ago
            else:
                rd_diff_usage = 0
                wr_diff_usage = 0
            dev_usage.append({'dev': dev[1], 'rd': rd_diff_usage, 'wr': wr_diff_usage})
        return dev_usage

    def net_usage(self):
        devices = []
        dev_usage = []
        if self.get_status() == 1:
            tree = ElementTree.fromstring(self._XMLDesc(0))
            for target in tree.findall("devices/interface/target"):
                devices.append(target.get("dev"))
            for i, dev in enumerate(devices):
                rx_use_ago = self.instance.interfaceStats(dev)[0]
                tx_use_ago = self.instance.interfaceStats(dev)[4]
                time.sleep(1)
                rx_use_now = self.instance.interfaceStats(dev)[0]
                tx_use_now = self.instance.interfaceStats(dev)[4]
                rx_diff_usage = (rx_use_now - rx_use_ago) * 8
                tx_diff_usage = (tx_use_now - tx_use_ago) * 8
                dev_usage.append({'dev': i, 'rx': rx_diff_usage, 'tx': tx_diff_usage})
        else:
            for i, dev in enumerate(self.get_net_device()):
                dev_usage.append({'dev': i, 'rx': 0, 'tx': 0})
        return dev_usage

    def get_telnet_port(self):
        telnet_port = None
        service_port = None
        tree = ElementTree.fromstring(self._XMLDesc(0))
        for console in tree.findall('devices/console'):
            if console.get('type') == 'tcp':
                for elm in console:
                    if elm.tag == 'source':
                        if elm.get('service'):
                            service_port = elm.get('service')
                    if elm.tag == 'protocol':
                        if elm.get('type') == 'telnet':
                            if service_port is not None:
                                telnet_port = service_port
        return telnet_port

    def get_console_listen_addr(self):
        listen_addr = util.get_xml_path(self._XMLDesc(0),
                                        "/domain/devices/graphics/@listen")
        if listen_addr is None:
            listen_addr = util.get_xml_path(self._XMLDesc(0),
                                            "/domain/devices/graphics/listen/@address")
            if listen_addr is None:
                    return "127.0.0.1"
        return listen_addr

    def set_console_listen_addr(self, listen_addr):
        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        root = ElementTree.fromstring(xml)
        console_type = self.get_console_type()
        try:
            graphic = root.find("devices/graphics[@type='%s']" % console_type)
        except SyntaxError:
            # Little fix for old version ElementTree
            graphic = root.find("devices/graphics")
        if graphic is None:
            return False
        listen = graphic.find("listen[@type='address']")
        if listen is None:
            return False
        if listen_addr:
            graphic.set("listen", listen_addr)
            listen.set("address", listen_addr)
        else:
            try:
                graphic.attrib.pop("listen")
                listen.attrib.pop("address")
            except:
                pass
        newxml = ElementTree.tostring(root)
        return self._defineXML(newxml)
    
    def get_console_socket(self):
        socket = util.get_xml_path(self._XMLDesc(0), "/domain/devices/graphics/@socket")
        return socket

    def get_console_type(self):
        console_type = util.get_xml_path(self._XMLDesc(0),"/domain/devices/graphics/@type")
        return console_type

    def set_console_type(self, console_type):
        current_type = self.get_console_type()
        if current_type == console_type:
            return True
        if console_type == '' or console_type not in QEMU_CONSOLE_TYPES:
            return False
        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        root = ElementTree.fromstring(xml)
        try:
            graphic = root.find("devices/graphics[@type='%s']" % current_type)
        except SyntaxError:
            # Little fix for old version ElementTree
            graphic = root.find("devices/graphics")
        graphic.set('type', console_type)
        newxml = ElementTree.tostring(root)
        self._defineXML(newxml)

    def get_console_port(self, console_type=None):
        if console_type is None:
            console_type = self.get_console_type()
        port = util.get_xml_path(self._XMLDesc(0),
                                 "/domain/devices/graphics[@type='%s']/@port" % console_type)
        return port

    def get_console_websocket_port(self):
        console_type = self.get_console_type()
        websocket_port = util.get_xml_path(self._XMLDesc(0),
                                           "/domain/devices/graphics[@type='%s']/@websocket" % console_type)
        return websocket_port

    def get_console_passwd(self):
        return util.get_xml_path(self._XMLDesc(VIR_DOMAIN_XML_SECURE),
                                 "/domain/devices/graphics/@passwd")

    def set_console_passwd(self, passwd):
        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        root = ElementTree.fromstring(xml)
        console_type = self.get_console_type()
        try:
            graphic = root.find("devices/graphics[@type='%s']" % console_type)
        except SyntaxError:
            # Little fix for old version ElementTree
            graphic = root.find("devices/graphics")
        if graphic is None:
            return False
        if passwd:
            graphic.set('passwd', passwd)
        else:
            try:
                graphic.attrib.pop('passwd')
            except:
                pass
        newxml = ElementTree.tostring(root)
        return self._defineXML(newxml)

    def set_console_keymap(self, keymap):
        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        root = ElementTree.fromstring(xml)
        console_type = self.get_console_type()
        try:
            graphic = root.find("devices/graphics[@type='%s']" % console_type)
        except SyntaxError:
            # Little fix for old version ElementTree
            graphic = root.find("devices/graphics")
        if keymap:
            graphic.set('keymap', keymap)
        else:
            try:
                graphic.attrib.pop('keymap')
            except:
                pass
        newxml = ElementTree.tostring(root)
        self._defineXML(newxml)

    def get_console_keymap(self):
        return util.get_xml_path(self._XMLDesc(VIR_DOMAIN_XML_SECURE),
                                 "/domain/devices/graphics/@keymap") or ''

    def resize(self, cur_memory, memory, cur_vcpu, vcpu, disks=[]):
        """
        Function change ram and cpu on vds.
        """
        memory = int(memory) * 1024
        cur_memory = int(cur_memory) * 1024

        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        tree = ElementTree.fromstring(xml)

        set_mem = tree.find('memory')
        set_mem.text = str(memory)
        set_cur_mem = tree.find('currentMemory')
        set_cur_mem.text = str(cur_memory)
        set_vcpu = tree.find('vcpu')
        set_vcpu.text = vcpu
        set_vcpu.set('current', cur_vcpu)

        for disk in disks:
            source_dev = disk['path']
            vol = self.get_volume_by_path(source_dev)
            vol.resize(disk['size_new'])
        
        new_xml = ElementTree.tostring(tree)
        self._defineXML(new_xml)

    def get_iso_media(self):
        iso = []
        storages = self.get_storages(only_actives=True)
        for storage in storages:
            stg = self.get_storage(storage)
            if stg.info()[0] != 0:
                try:
                    stg.refresh(0)
                except:
                    pass
                for img in stg.listVolumes():
                    if img.endswith('.iso'):
                        iso.append(img)
        return iso

    def delete_all_disks(self):
        disks = self.get_disk_devices()
        for disk in disks:
            vol = self.get_volume_by_path(disk.get('path'))
            vol.delete(0)

    def _snapshotCreateXML(self, xml, flag):
        self.instance.snapshotCreateXML(xml, flag)

    def create_snapshot(self, name):
        xml = """<domainsnapshot>
                     <name>%s</name>
                     <state>shutoff</state>
                     <creationTime>%d</creationTime>""" % (name, time.time())
        xml += self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        xml += """<active>0</active>
                  </domainsnapshot>"""
        self._snapshotCreateXML(xml, 0)

    def get_snapshot(self):
        snapshots = []
        snapshot_list = self.instance.snapshotListNames(0)
        for snapshot in snapshot_list:
            snap = self.instance.snapshotLookupByName(snapshot, 0)
            snap_time_create = util.get_xml_path(snap.getXMLDesc(0), "/domainsnapshot/creationTime")
            snapshots.append({'date': datetime.fromtimestamp(int(snap_time_create)), 'name': snapshot})
        return snapshots

    def snapshot_delete(self, snapshot):
        snap = self.instance.snapshotLookupByName(snapshot, 0)
        snap.delete(0)

    def snapshot_revert(self, snapshot):
        snap = self.instance.snapshotLookupByName(snapshot, 0)
        self.instance.revertToSnapshot(snap, 0)

    def get_managed_save_image(self):
        return self.instance.hasManagedSaveImage(0)

    def get_wvmStorage(self, pool):
        storage = wvmStorage(self.host,
                             self.login,
                             self.passwd,
                             self.conn,
                             pool)
        return storage

    def fix_mac(self, mac):
        if ":" in mac:
            return mac
        # if mac does not contain ":", try to split into tuples and join with ":"
        n = 2
        mac_tuples = [mac[i:i+n] for i in range(0, len(mac), n)]
        return ':'.join(mac_tuples)

    def clone_instance(self, clone_data):
        clone_dev_path = []

        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        tree = ElementTree.fromstring(xml)
        name = tree.find('name')
        name.text = clone_data['name']
        uuid = tree.find('uuid')
        tree.remove(uuid)

        for num, net in enumerate(tree.findall('devices/interface')):
            elm = net.find('mac')
            mac_address = self.fix_mac(clone_data['clone-net-mac-' + str(num)])
            elm.set('address', mac_address)

        for disk in tree.findall('devices/disk'):
            if disk.get('device') == 'disk':
                elm = disk.find('target')
                device_name = elm.get('dev')
                if device_name:
                    target_file = clone_data['disk-' + device_name]
                    try:
                        meta_prealloc = clone_data['meta-' + device_name]
                    except:
                        meta_prealloc = False
                    elm.set('dev', device_name)

                elm = disk.find('source')
                source_file = elm.get('file')
                if source_file:
                    clone_dev_path.append(source_file)
                    clone_path = os.path.join(os.path.dirname(source_file), target_file)
                    elm.set('file', clone_path)

                    vol = self.get_volume_by_path(source_file)
                    vol_format = util.get_xml_path(vol.XMLDesc(0), "/volume/target/format/@type")

                    if vol_format == 'qcow2' and meta_prealloc:
                        meta_prealloc = True

                    vol_clone_xml = """
                                    <volume>
                                        <name>%s</name>
                                        <capacity>0</capacity>
                                        <allocation>0</allocation>
                                        <target>
                                            <format type='%s'/>
                                        </target>
                                        <permissions>
                                            <owner>%s</owner>
                                            <group>%s</group>
                                            <mode>0644</mode>
                                            <label>virt_image_t</label>
                                        </permissions>
                                        <compat>1.1</compat>
                                        <features>
                                            <lazy_refcounts/>
                                        </features>
                                    </volume>""" % (target_file, vol_format, owner['uid'], owner['guid'])
                    stg = vol.storagePoolLookupByVolume()
                    stg.createXMLFrom(vol_clone_xml, vol, meta_prealloc)
                
                source_protocol = elm.get('protocol')
                if source_protocol == 'rbd':
                    source_name = elm.get('name')
                    clone_name = "%s/%s" % (os.path.dirname(source_name), target_file)
                    elm.set('name', clone_name)

                    vol = self.get_volume_by_path(source_name)
                    vol_format = util.get_xml_path(vol.XMLDesc(0), "/volume/target/format/@type")

                    vol_clone_xml = """
                                    <volume type='network'>
                                        <name>%s</name>
                                        <capacity>0</capacity>
                                        <allocation>0</allocation>
                                        <target>
                                            <format type='%s'/>
                                        </target>
                                    </volume>""" % (target_file, vol_format)
                    stg = vol.storagePoolLookupByVolume()
                    stg.createXMLFrom(vol_clone_xml, vol, meta_prealloc)

                source_dev = elm.get('dev')
                if source_dev:
                    clone_path = os.path.join(os.path.dirname(source_dev), target_file)
                    elm.set('dev', clone_path)
                    
                    vol = self.get_volume_by_path(source_dev)
                    stg = vol.storagePoolLookupByVolume()
                    
                    vol_name = util.get_xml_path(vol.XMLDesc(0), "/volume/name")
                    pool_name = util.get_xml_path(stg.XMLDesc(0), "/pool/name")
                    
                    storage = self.get_wvmStorage(pool_name)
                    storage.clone_volume(vol_name, target_file)

        options = {
            'title': clone_data.get('clone-title', ''),
            'description': clone_data.get('clone-description', ''),
        }
        self._set_options(tree, options)
        self._defineXML(ElementTree.tostring(tree))

        return self.get_instance(clone_data['name']).UUIDString()

    def get_bridge_name(self, source, source_type='net'):
        if source_type == 'iface':
            iface = self.get_iface(source)
            bridge_name = iface.name()
        else:
            net = self.get_network(source)
            bridge_name = net.bridgeName()
        return bridge_name
        
    def add_network(self, mac_address, source, source_type='net', interface_type='bridge', model='virtio', nwfilter=None):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        bridge_name = self.get_bridge_name(source, source_type)
        xml_interface = """
        <interface type='%s'>
          <mac address='%s'/>
          <source bridge='%s'/>
          <model type='%s'/>
          """ % (interface_type, mac_address, bridge_name, model)
        if nwfilter:
            xml_interface += """
            <filterref filter='%s'/>
            """ % nwfilter
        xml_interface += """</interface>"""

        if self.get_status() == 5:
            devices = tree.find('devices')
            elm_interface = ElementTree.fromstring(xml_interface)
            devices.append(elm_interface)
            xmldom = ElementTree.tostring(tree)
            self._defineXML(xmldom)

    def delete_network(self, mac_address):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        devices = tree.find('devices')
        for interface in tree.findall('devices/interface'):
            source = interface.find('mac')
            if source.get('address', '') == mac_address:
                source = None
                devices.remove(interface)
                new_xml = ElementTree.tostring(tree)
                self._defineXML(new_xml)

    def change_network(self, network_data):
        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        tree = ElementTree.fromstring(xml)
        for num, interface in enumerate(tree.findall('devices/interface')):
            net_source = network_data['net-source-' + str(num)]
            net_source_type = network_data['net-source-' + str(num) + '-type']
            net_mac = network_data['net-mac-' + str(num)]
            net_filter = network_data['net-nwfilter-' + str(num)]
            bridge_name = self.get_bridge_name(net_source, net_source_type)
            if interface.get('type') == 'bridge':
                source = interface.find('mac')
                source.set('address', net_mac)
                source = interface.find('source')
                source.set('bridge', bridge_name)
                source = interface.find('filterref')

                if net_filter:
                    if source is not None: source.set('filter', net_filter)
                    else:
                        element = ElementTree.Element("filterref")
                        element.attrib['filter'] = net_filter
                        interface.append(element)
                else:
                    if source is not None: interface.remove(source)

        new_xml = ElementTree.tostring(tree)
        self._defineXML(new_xml)

    def _set_options(self, tree, options):
        for o in ['title', 'description']:
            option = tree.find(o)
            option_value = options.get(o, '').strip()
            if not option_value:
                if not option is None:
                    tree.remove(option)
            else:
                if option is None:
                    option = ElementTree.SubElement(tree, o)
                option.text = option_value

    def set_options(self, options):
        """
        Function change description, title
        """
        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        tree = ElementTree.fromstring(xml)

        self._set_options(tree, options)

        new_xml = ElementTree.tostring(tree)
        self._defineXML(new_xml)

