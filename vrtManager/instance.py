import contextlib
import json
import os.path
import time

try:
    from libvirt import (
        VIR_DOMAIN_AFFECT_CONFIG,
        VIR_DOMAIN_AFFECT_LIVE,
        VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT,
        VIR_DOMAIN_RUNNING,
        VIR_DOMAIN_XML_SECURE,
        VIR_MIGRATE_AUTO_CONVERGE,
        VIR_MIGRATE_COMPRESSED,
        VIR_MIGRATE_LIVE,
        VIR_MIGRATE_OFFLINE,
        VIR_MIGRATE_PERSIST_DEST,
        VIR_MIGRATE_POSTCOPY,
        VIR_MIGRATE_UNDEFINE_SOURCE,
        VIR_MIGRATE_UNSAFE,
        VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY,
        VIR_DOMAIN_SNAPSHOT_DELETE_METADATA_ONLY,
        VIR_DOMAIN_SNAPSHOT_LIST_INTERNAL,
        VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL,
        VIR_DOMAIN_BLOCK_COMMIT_DELETE,
        VIR_DOMAIN_BLOCK_COMMIT_ACTIVE,
        VIR_DOMAIN_BLOCK_JOB_ABORT_PIVOT,
        VIR_DOMAIN_START_PAUSED,
        libvirtError,
    )
    from libvirt_qemu import VIR_DOMAIN_QEMU_AGENT_COMMAND_DEFAULT, qemuAgentCommand
except Exception:
    from libvirt import libvirtError, VIR_DOMAIN_XML_SECURE, VIR_MIGRATE_LIVE

from collections import OrderedDict
from datetime import datetime
from xml.etree import ElementTree

from lxml import etree

from vrtManager import util
from vrtManager.connection import wvmConnect
from vrtManager.storage import wvmStorage, wvmStorages

class wvmInstances(wvmConnect):
    def get_instance_status(self, name):
        inst = self.get_instance(name)
        return inst.info()[0]

    def get_instance_memory(self, name):
        inst = self.get_instance(name)
        mem = util.get_xml_path(inst.XMLDesc(0), "/domain/currentMemory")
        return int(mem) // 1024

    def get_instance_vcpu(self, name):
        inst = self.get_instance(name)
        cur_vcpu = util.get_xml_path(inst.XMLDesc(0), "/domain/vcpu/@current")
        return cur_vcpu or util.get_xml_path(inst.XMLDesc(0), "/domain/vcpu")

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

    def moveto(
        self,
        conn,
        name,
        live,
        unsafe,
        undefine,
        offline,
        autoconverge=False,
        compress=False,
        postcopy=False,
    ):
        flags = VIR_MIGRATE_PERSIST_DEST
        if live and conn.get_status() != 5:
            flags |= VIR_MIGRATE_LIVE
        if unsafe and conn.get_status() == 1:
            flags |= VIR_MIGRATE_UNSAFE
        if offline and conn.get_status() == 5:
            flags |= VIR_MIGRATE_OFFLINE
        if not offline and autoconverge:
            flags |= VIR_MIGRATE_AUTO_CONVERGE
        if not offline and compress and conn.get_status() == 1:
            flags |= VIR_MIGRATE_COMPRESSED
        if not offline and postcopy and conn.get_status() == 1:
            flags |= VIR_MIGRATE_POSTCOPY
        if undefine:
            flags |= VIR_MIGRATE_UNDEFINE_SOURCE

        dom = conn.get_instance(name)

        dom_arch = conn.get_arch()
        dom_emulator = conn.get_dom_emulator()

        if dom_emulator != self.get_emulator(dom_arch):
            raise libvirtError(
                "Destination host emulator is different. Cannot be migrated"
            )

        dom.migrate(self.wvm, flags, None, None, 0)

    def graphics_type(self, name):
        inst = self.get_instance(name)
        console_type = util.get_xml_path(
            inst.XMLDesc(0), "/domain/devices/graphics/@type"
        )
        return "None" if console_type is None else console_type

    def graphics_listen(self, name):
        inst = self.get_instance(name)
        listener_addr = util.get_xml_path(
            inst.XMLDesc(0), "/domain/devices/graphics/@listen"
        )
        if listener_addr is None:
            listener_addr = util.get_xml_path(
                inst.XMLDesc(0), "/domain/devices/graphics/listen/@address"
            )
        return "None" if listener_addr is None else listener_addr

    def graphics_port(self, name):
        inst = self.get_instance(name)
        console_port = util.get_xml_path(
            inst.XMLDesc(0), "/domain/devices/graphics/@port"
        )
        return "None" if console_port is None else console_port

    def domain_name(self, name):
        inst = self.get_instance(name)
        domname = util.get_xml_path(inst.XMLDesc(0), "/domain/name")
        return "NoName" if domname is None else domname

    def graphics_passwd(self, name):
        inst = self.get_instance(name)
        password = util.get_xml_path(
            inst.XMLDesc(VIR_DOMAIN_XML_SECURE), "/domain/devices/graphics/@passwd"
        )
        return "None" if password is None else password


class wvmInstance(wvmConnect):
    def __init__(self, host, login, passwd, conn, vname):
        wvmConnect.__init__(self, host, login, passwd, conn)
        self._ip_cache = None
        self.instance = self.get_instance(vname)

    def osinfo(self):
        info_results = qemuAgentCommand(
            self.instance,
            '{"execute":"guest-get-osinfo"}',
            VIR_DOMAIN_QEMU_AGENT_COMMAND_DEFAULT,
            0,
        )

        timezone_results = qemuAgentCommand(
            self.instance,
            '{"execute":"guest-get-timezone"}',
            VIR_DOMAIN_QEMU_AGENT_COMMAND_DEFAULT,
            0,
        )

        hostname_results = qemuAgentCommand(
            self.instance,
            '{"execute":"guest-get-host-name"}',
            VIR_DOMAIN_QEMU_AGENT_COMMAND_DEFAULT,
            0,
        )

        info_results = json.loads(info_results).get("return")

        timezone_results = json.loads(timezone_results).get("return")
        hostname_results = json.loads(hostname_results).get("return")

        info_results.update(timezone_results)
        info_results.update(hostname_results)

        return info_results

    def start(self, flags=0):
        self.instance.createWithFlags(flags)

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

    def delete(self, flags=0):
        self.instance.undefineFlags(flags)

    def _XMLDesc(self, flag):
        return self.instance.XMLDesc(flag)

    def _defineXML(self, xml):
        return self.wvm.defineXML(xml)

    def get_status(self):
        """
        VIR_DOMAIN_NOSTATE = 0
        VIR_DOMAIN_RUNNING = 1
        VIR_DOMAIN_PAUSED = 3
        VIR_DOMAIN_SHUTOFF = 5
        """
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
        return int(cur_vcpu) if cur_vcpu else self.get_vcpu()

    def get_vcpu_mode(self):
        return util.get_xml_path(self._XMLDesc(0), "/domain/cpu/@current")

    def get_arch(self):
        return util.get_xml_path(self._XMLDesc(0), "/domain/os/type/@arch")

    def get_machine_type(self):
        return util.get_xml_path(self._XMLDesc(0), "/domain/os/type/@machine")

    def get_dom_emulator(self):
        return util.get_xml_path(self._XMLDesc(0), "/domain/devices/emulator")

    def get_nvram(self):
        return util.get_xml_path(self._XMLDesc(0), "/domain/os/nvram")

    def get_loader(self):
        xml = self._XMLDesc(0)
        loader = util.get_xml_path(xml, "/domain/os/loader")
        loader_type = util.get_xml_path(xml, "/domain/os/loader/@type")
        readonly = util.get_xml_path(xml, "/domain/os/loader/@readonly")
        return {"loader": loader, "type": loader_type, "readonly": readonly}

    def get_vcpus(self):
        vcpus = OrderedDict()
        tree = etree.fromstring(self._XMLDesc(0))
        for vcpu in tree.xpath("/domain/vcpus/vcpu"):
            vcpu_id = vcpu.get("id")
            enabled = vcpu.get("enabled")
            hotplug = vcpu.get("hotpluggable")
            order = vcpu.get("order")
            vcpus[vcpu_id] = {
                "enabled": enabled,
                "hotpluggable": hotplug,
                "order": order,
            }

        return vcpus

    def get_memory(self):
        mem = util.get_xml_path(self._XMLDesc(0), "/domain/memory")
        return int(mem) // 1024

    def get_cur_memory(self):
        mem = util.get_xml_path(self._XMLDesc(0), "/domain/currentMemory")
        return int(mem) // 1024

    def get_title(self):
        title = util.get_xml_path(self._XMLDesc(0), "/domain/title")
        return title or ""

    def get_filterrefs(self):
        def filterrefs(ctx):
            result = []
            for net in ctx.xpath("/domain/devices/interface"):
                filterref = net.xpath("filterref/@filter")
                if filterref:
                    result.append(filterref[0])
            return result

        return util.get_xml_path(self._XMLDesc(0), func=filterrefs)

    def get_description(self):
        description = util.get_xml_path(self._XMLDesc(0), "/domain/description")
        return description or ""

    def get_max_memory(self):
        return self.wvm.getInfo()[1] * 1048576

    def get_max_cpus(self):
        """Get number of physical CPUs."""
        hostinfo = self.wvm.getInfo()
        pcpus = hostinfo[4] * hostinfo[5] * hostinfo[6] * hostinfo[7]
        return range(1, int(pcpus + 1))

    def get_interface_addresses(self, iface_mac):
        if self._ip_cache is None:
            self.refresh_interface_addresses()

        qemuga = self._ip_cache["qemuga"]
        arp = self._ip_cache["arp"]
        leases = []

        def extract_dom(info):
            ipv4 = []
            ipv6 = []
            for addrs in info.values():
                if addrs["hwaddr"] != iface_mac:
                    continue
                if not addrs["addrs"]:
                    continue
                for addr in addrs["addrs"]:
                    if addr["type"] == 0:
                        ipv4.append(addr["addr"])
                    elif addr["type"] == 1 and not str(addr["addr"]).startswith("fe80"):
                        ipv6.append(addr["addr"] + "/" + str(addr["prefix"]))
            return ipv4, ipv6

        def extract_lease(info):
            ipv4 = []
            ipv6 = []
            if info["mac"] == iface_mac:
                if info["type"] == 0:
                    ipv4.append(info["ipaddr"])
                elif info["type"] == 1:
                    ipv6.append(info["ipaddr"])
            return ipv4, ipv6

        for ips in [qemuga] + leases + [arp]:
            ipv4, ipv6 = extract_lease(ips) if "expirytime" in ips else extract_dom(ips)
            if ipv4 or ipv6:
                return ipv4, ipv6
        return None, None

    def _get_interface_addresses(self, source):
        # ("Calling interfaceAddresses source=%s", source)
        with contextlib.suppress(libvirtError):
            return self.instance.interfaceAddresses(source)
        return {}

    def refresh_interface_addresses(self):
        self._ip_cache = {"qemuga": {}, "arp": {}}

        if self.get_status() != 1:
            return

        if self.is_agent_ready():
            self._ip_cache["qemuga"] = self._get_interface_addresses(
                VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT
            )

        arp_flag = 3  # libvirt."VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP"
        self._ip_cache["arp"] = self._get_interface_addresses(arp_flag)

    def get_net_devices(self):
        def networks(ctx):
            result = []
            inbound = outbound = []
            for net in ctx.xpath("/domain/devices/interface"):
                interface_type = net.xpath("@type")[0]
                mac_inst = net.xpath("mac/@address")[0]
                nic_inst = net.xpath("source/@network|source/@bridge|source/@dev")[0]
                target_inst = net.xpath("target/@dev")[0] if net.xpath("target/@dev") else ""
                link_state = net.xpath("link/@state")[0] if net.xpath("link") else "up"
                filterref_inst = net.xpath("filterref/@filter")[0] if net.xpath("filterref/@filter") else ""

                model_type = net.xpath("model/@type")[0]
                if net.xpath("bandwidth/inbound"):
                    in_attr = net.xpath("bandwidth/inbound")[0]
                    in_av = in_attr.get("average")
                    in_peak = in_attr.get("peak")
                    in_burst = in_attr.get("burst")
                    inbound = {"average": in_av, "peak": in_peak, "burst": in_burst}
                if net.xpath("bandwidth/outbound"):
                    out_attr = net.xpath("bandwidth/outbound")[0]
                    out_av = out_attr.get("average")
                    out_peak = out_attr.get("peak")
                    out_burst = out_attr.get("burst")
                    outbound = {"average": out_av, "peak": out_peak, "burst": out_burst}

                try:
                    ipv4, ipv6 = self.get_interface_addresses(mac_inst)
                except libvirtError:
                    ipv4, ipv6 = None, None
                result.append(
                    {
                        "type": interface_type,
                        "mac": mac_inst,
                        "nic": nic_inst,
                        "target": target_inst,
                        "state": link_state,
                        "model": model_type,
                        "ipv4": ipv4,
                        "ipv6": ipv6,
                        "filterref": filterref_inst,
                        "inbound": inbound,
                        "outbound": outbound,
                    }
                )
            return result

        return util.get_xml_path(self._XMLDesc(0), func=networks)

    def get_disk_devices(self):
        def disks(doc):
            result = []

            for disk in doc.xpath("/domain/devices/disk"):
                dev = volume = storage = src_file = bus = None
                disk_format = used_size = disk_size = None
                disk_cache = disk_io = disk_discard = disk_zeroes = "default"
                readonly = shareable = serial = None
                backing_file = None

                device = disk.xpath("@device")[0]
                if device == "disk":
                    try:
                        dev = disk.xpath("target/@dev")[0]
                        bus = disk.xpath("target/@bus")[0]
                        try:
                            src_file = disk.xpath(
                                "source/@file|source/@dev|source/@name"
                            )[0]
                        except Exception:
                            v = disk.xpath("source/@volume")[0]
                            s_name = disk.xpath("source/@pool")[0]
                            s = self.wvm.storagePoolLookupByName(s_name)
                            src_file = s.storageVolLookupByName(v).path()

                        with contextlib.suppress(Exception):
                            disk_format = disk.xpath("driver/@type")[0]

                        with contextlib.suppress(Exception):
                            disk_cache = disk.xpath("driver/@cache")[0]

                        with contextlib.suppress(Exception):
                            disk_io = disk.xpath("driver/@io")[0]

                        with contextlib.suppress(Exception):
                            disk_discard = disk.xpath("driver/@discard")[0]

                        with contextlib.suppress(Exception):
                            disk_zeroes = disk.xpath("driver/@detect_zeroes")[0]

                        with contextlib.suppress(Exception):
                            backing_file = disk.xpath("backingStore/source/@file")[0]

                        readonly = bool(disk.xpath("readonly"))
                        shareable = bool(disk.xpath("shareable"))
                        serial = (
                            disk.xpath("serial")[0].text
                            if disk.xpath("serial")
                            else None
                        )

                        try:
                            vol = self.get_volume_by_path(src_file)
                            volume = vol.name()

                            disk_size = vol.info()[1]
                            used_size = vol.info()[2]
                            stg = vol.storagePoolLookupByVolume()
                            storage = stg.name()
                        except libvirtError:
                            volume = src_file
                    except Exception as e:
                        print(f"Exception: {e}")
                    finally:
                        result.append(
                            {
                                "dev": dev,
                                "bus": bus,
                                "image": volume,
                                "storage": storage,
                                "path": src_file,
                                "format": disk_format,
                                "backing_file": backing_file,
                                "size": disk_size,
                                "used": used_size,
                                "cache": disk_cache,
                                "io": disk_io,
                                "discard": disk_discard,
                                "detect_zeroes": disk_zeroes,
                                "readonly": readonly,
                                "shareable": shareable,
                                "serial": serial,
                            }
                        )
            return result

        return util.get_xml_path(self._XMLDesc(0), func=disks)

    def get_media_devices(self):
        def disks(doc):
            result = []
            dev = volume = storage = bus = None
            src_file = None
            for media in doc.xpath("/domain/devices/disk"):
                device = media.xpath("@device")[0]
                if device == "cdrom":
                    try:
                        dev = media.xpath("target/@dev")[0]
                        bus = media.xpath("target/@bus")[0]
                        src_file = None
                        volume = src_file
                        with contextlib.suppress(Exception):
                            src_file = media.xpath("source/@file")[0]
                            vol = self.get_volume_by_path(src_file)
                            volume = vol.name()
                            stg = vol.storagePoolLookupByVolume()
                            storage = stg.name()
                    except Exception:
                        pass
                    finally:
                        result.append(
                            {
                                "dev": dev,
                                "image": volume,
                                "storage": storage,
                                "path": src_file,
                                "bus": bus,
                            }
                        )
            return result

        return util.get_xml_path(self._XMLDesc(0), func=disks)

    def get_bootmenu(self):
        menu = util.get_xml_path(self._XMLDesc(0), "/domain/os/bootmenu/@enable")
        return menu == "yes"

    def set_bootmenu(self, flag):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        os = tree.find("os")
        menu = os.find("bootmenu")

        if menu is None:
            bootmenu = ElementTree.fromstring("<bootmenu enable='yes'/>")
            os.append(bootmenu)
            menu = os.find("bootmenu")

        if flag == 0:  # Disable
            menu.attrib["enable"] = "no"
        elif flag == 1:  # Enable
            menu.attrib["enable"] = "yes"
        elif flag == -1:  # Remove
            os.remove(menu)
        else:
            raise Exception(
                "Unknown boot menu option, please choose one of 0:disable, 1:enable, -1:remove"
            )

        xmldom = ElementTree.tostring(tree).decode()
        self._defineXML(xmldom)

    def get_bootorder(self):
        boot_order = {}
        dev_type = target = None
        tree = ElementTree.fromstring(self._XMLDesc(0))
        os = tree.find("os")
        boot = os.findall("boot")

        for idx, b in enumerate(boot):
            dev = b.get("dev")
            if dev == "cdrom":
                target = "cdrom"
                dev_type = "file"
            elif dev == "fd":
                target = "floppy"
                dev_type = "file"
            elif dev == "hd":
                target = "disk"
                dev_type = "file"
            elif dev == "network":
                target = "network"
                dev_type = "network"
            boot_order[idx] = {"type": dev_type, "dev": dev, "target": target}

        devices = tree.find("devices")
        for dev in devices:
            dev_target = None
            boot_dev = dev.find("boot")
            if boot_dev is not None:
                idx = boot_dev.get("order")
                dev_type = dev.get("type")
                dev_device = dev.get("device")

                if dev_type == "file":
                    dev_target = dev.find("target").get("dev")

                elif dev_type == "network":
                    dev_mac = dev.find("mac").get("address")
                    dev_device = "network"
                    dev_target = f"nic-{dev_mac[9:]}"
                # pass dev_type usb
                boot_order[int(idx) - 1] = {
                    "type": dev_type,
                    "dev": dev_device,
                    "target": dev_target,
                }

        return boot_order

    def set_bootorder(self, devorder):
        if not devorder:
            return

        def remove_bootorder():
            tree = ElementTree.fromstring(self._XMLDesc(0))
            os = tree.find("os")
            boot = os.findall("boot")
            # Remove old style boot order
            for b in boot:
                os.remove(b)
            # Remove rest of them
            for dev in tree.find("devices"):
                boot_dev = dev.find("boot")
                if boot_dev is not None:
                    dev.remove(boot_dev)
            return tree

        tree = remove_bootorder()

        for idx, dev in devorder.items():
            order = ElementTree.fromstring("<boot order='{}'/>".format(idx + 1))
            if dev["type"] == "disk":
                devices = tree.findall("./devices/disk[@device='disk']")
                for d in devices:
                    device = d.find("./target[@dev='{}']".format(dev["dev"]))
                    if device is not None:
                        d.append(order)
            elif dev["type"] == "cdrom":
                devices = tree.findall("./devices/disk[@device='cdrom']")
                for d in devices:
                    device = d.find("./target[@dev='{}']".format(dev["dev"]))
                    if device is not None:
                        d.append(order)
            elif dev["type"] == "network":
                devices = tree.findall("./devices/interface[@type='network']")
                for d in devices:
                    device = d.find("mac[@address='{}']".format(dev["dev"]))
                    if device is not None:
                        d.append(order)
            else:
                raise Exception("Invalid Device Type for boot order")
        self._defineXML(ElementTree.tostring(tree).decode())

    def mount_iso(self, dev, image):
        def attach_iso(dev, disk, vol):
            if disk.get("device") == "cdrom":
                for elm in disk:
                    if elm.tag == "target" and elm.get("dev") == dev:
                        src_media = ElementTree.Element("source")
                        src_media.set("file", vol.path())
                        disk.insert(2, src_media)
                        return True

        vol = None
        storages = self.get_storages(only_actives=True)
        for storage in storages:
            stg = self.get_storage(storage)
            if stg.info()[0] != 0:
                for img in stg.listVolumes():
                    if image == img:
                        vol = stg.storageVolLookupByName(image)
        tree = ElementTree.fromstring(self._XMLDesc(0))
        for disk in tree.findall("devices/disk"):
            if attach_iso(dev, disk, vol):
                break
        if self.get_status() == 1:
            xml = ElementTree.tostring(disk).decode()
            self.instance.attachDevice(xml)
            xmldom = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        if self.get_status() == 5:
            xmldom = ElementTree.tostring(tree).decode()
        self._defineXML(xmldom)

    def umount_iso(self, dev, image):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        for disk in tree.findall("devices/disk"):
            if disk.get("device") == "cdrom":
                for elm in disk:
                    if elm.tag == "source" and elm.get("file") == image:
                        src_media = elm
                    if elm.tag == "target" and elm.get("dev") == dev:
                        disk.remove(src_media)
        if self.get_status() == 1:
            xml_disk = ElementTree.tostring(disk).decode()
            self.instance.attachDevice(xml_disk)
            xmldom = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        if self.get_status() == 5:
            xmldom = ElementTree.tostring(tree).decode()
        self._defineXML(xmldom)

    def attach_disk(
        self,
        target_dev,
        source,
        source_info=None,
        pool_type="dir",
        target_bus="ide",
        disk_type="file",
        disk_device="disk",
        driver_name="qemu",
        format_type="raw",
        readonly=False,
        shareable=False,
        serial=None,
        cache_mode=None,
        io_mode=None,
        discard_mode=None,
        detect_zeroes_mode=None,
    ):

        additionals = ""
        if (
            cache_mode is not None
            and cache_mode != "default"
            and disk_device != "cdrom"
        ):
            additionals += f"cache='{cache_mode}' "
        if io_mode is not None and io_mode != "default":
            additionals += f"io='{io_mode}' "
        if discard_mode is not None and discard_mode != "default":
            additionals += f"discard='{discard_mode}' "
        if detect_zeroes_mode is not None and detect_zeroes_mode != "default":
            additionals += f"detect_zeroes='{detect_zeroes_mode}' "

        xml_disk = f"<disk type='{disk_type}' device='{disk_device}'>"
        if disk_device == "cdrom":
            xml_disk += f"<driver name='{driver_name}' type='{format_type}'/>"
        elif disk_device == "disk":
            xml_disk += (
                f"<driver name='{driver_name}' type='{format_type}' {additionals}/>"
            )

        if disk_type == "file":
            xml_disk += f"<source file='{source}'/>"
        elif disk_type == "network":
            if pool_type == "rbd":
                auth_type = source_info.get("auth_type")
                auth_user = source_info.get("auth_user")
                auth_uuid = source_info.get("auth_uuid")
                xml_disk += f"""<auth username='{auth_user}'>
                                <secret type='{auth_type}' uuid='{auth_uuid}'/>
                            </auth>"""
                xml_disk += f"""<source protocol='{pool_type}' name='{source}'>"""
                for host in source_info.get("hosts"):
                    if host.get("hostport"):
                        xml_disk += f"""<host name="{host.get('hostname')}" port='{host.get('hostport')}'/>"""
                    else:
                        xml_disk += f"""<host name="{host.get('hostname')}"/>"""
                xml_disk += """</source>"""
            else:
                raise Exception("Not implemented disk type")
        else:
            raise Exception("Not implemented disk type")

        xml_disk += f"<target dev='{target_dev}' bus='{target_bus}'/>"
        if readonly or disk_device == "cdrom":
            xml_disk += """<readonly/>"""
        if shareable:
            xml_disk += """<shareable/>"""
        if serial is not None and serial != "None" and serial != "":
            xml_disk += f"""<serial>{serial}</serial>"""
        xml_disk += """</disk>"""
        if self.get_status() == 1:
            self.instance.attachDeviceFlags(xml_disk, VIR_DOMAIN_AFFECT_LIVE)
            self.instance.attachDeviceFlags(xml_disk, VIR_DOMAIN_AFFECT_CONFIG)
        if self.get_status() == 5:
            self.instance.attachDeviceFlags(xml_disk, VIR_DOMAIN_AFFECT_CONFIG)

    def detach_disk(self, target_dev):
        tree = etree.fromstring(self._XMLDesc(0))

        disk_el = tree.xpath("./devices/disk/target[@dev='{}']".format(target_dev))[
            0
        ].getparent()
        xml_disk = etree.tostring(disk_el).decode()
        devices = tree.find("devices")
        devices.remove(disk_el)

        if self.get_status() == 1:
            self.instance.detachDeviceFlags(xml_disk, VIR_DOMAIN_AFFECT_LIVE)
            self.instance.detachDeviceFlags(xml_disk, VIR_DOMAIN_AFFECT_CONFIG)
        if self.get_status() == 5:
            self.instance.detachDeviceFlags(xml_disk, VIR_DOMAIN_AFFECT_CONFIG)

    def edit_disk(
        self,
        target_dev,
        source,
        readonly,
        shareable,
        target_bus,
        serial,
        format,
        cache_mode,
        io_mode,
        discard_mode,
        detect_zeroes_mode,
    ):
        tree = etree.fromstring(self._XMLDesc(0))
        disk_el = tree.xpath("./devices/disk/target[@dev='{}']".format(target_dev))[
            0
        ].getparent()
        old_disk_type = disk_el.get("type")
        old_disk_device = disk_el.get("device")
        old_driver_name = disk_el.xpath("driver/@name")[0]
        old_target_bus = disk_el.xpath("target/@bus")[0]

        additionals = ""
        if cache_mode is not None and cache_mode != "default":
            additionals += f"cache='{cache_mode}' "
        if io_mode is not None and io_mode != "default":
            additionals += f"io='{io_mode}' "
        if discard_mode is not None and discard_mode != "default":
            additionals += f"discard='{discard_mode}' "
        if detect_zeroes_mode is not None and detect_zeroes_mode != "default":
            additionals += f"detect_zeroes='{detect_zeroes_mode}' "

        xml_disk = f"<disk type='{old_disk_type}' device='{old_disk_device}'>"
        if old_disk_device == "cdrom":
            xml_disk += f"<driver name='{old_driver_name}' type='{format}'/>"
        elif old_disk_device == "disk":
            xml_disk += (
                f"<driver name='{old_driver_name}' type='{format}' {additionals}/>"
            )

        xml_disk += f"""<source file='{source}'/>
          <target dev='{target_dev}' bus='{target_bus}'/>"""
        if readonly:
            xml_disk += """<readonly/>"""
        if shareable:
            xml_disk += """<shareable/>"""
        if serial is not None and serial != "None" and serial != "":
            xml_disk += f"""<serial>{serial}</serial>"""
        xml_disk += """</disk>"""

        self.instance.updateDeviceFlags(xml_disk, VIR_DOMAIN_AFFECT_CONFIG)

    def cpu_usage(self):
        cpu_usage = {}
        if self.get_status() == 1:
            nbcore = self.wvm.getInfo()[2]
            cpu_use_ago = self.instance.info()[4]
            time.sleep(1)
            cpu_use_now = self.instance.info()[4]
            diff_usage = cpu_use_now - cpu_use_ago
            cpu_usage["cpu"] = 100 * diff_usage / (1 * nbcore * 10**9)
        else:
            cpu_usage["cpu"] = 0
        return cpu_usage

    def set_vcpu(self, cpu_id, enabled):
        self.instance.setVcpu(str(cpu_id), enabled)

    def set_vcpu_hotplug(self, status, vcpus_hotplug=0):
        """vcpus_hotplug = 0 make all vpus hotpluggable"""
        vcpus_hotplug = int(self.get_vcpu()) if vcpus_hotplug == 0 else vcpus_hotplug
        if self.get_status() == 5:  # shutoff
            if status:
                xml = """ <vcpus>"""
                xml += """<vcpu id='0' enabled='yes' hotpluggable='no' order='1'/>"""
                for i in range(1, vcpus_hotplug):
                    xml += f"""<vcpu id='{i}' enabled='yes' hotpluggable='yes' order='{i+1}'/>"""
                xml += """</vcpus>"""

                tree = etree.fromstring(self._XMLDesc(0))
                vcpus = tree.xpath("/domain/vcpus")
                if not vcpus:
                    tree.append(etree.fromstring(xml))
                    self._defineXML(etree.tostring(tree).decode())
            else:
                tree = etree.fromstring(self._XMLDesc(0))
                vcpus = tree.xpath("/domain/vcpus")
                for vcpu in vcpus:
                    parent = vcpu.getparent()
                    parent.remove(vcpu)
                    self._defineXML(etree.tostring(tree).decode())
        else:
            raise libvirtError(
                "Please shutdown the instance then try to enable vCPU hotplug"
            )

    def mem_usage(self):
        mem_usage = {}
        if self.get_status() == 1:
            mem_stats = self.instance.memoryStats()
            rss = mem_stats["rss"] if "rss" in mem_stats else 0
            total = mem_stats["actual"] if "actual" in mem_stats else 0
            available = total - rss
            if available < 0:
                available = 0

            mem_usage["used"] = rss
            mem_usage["total"] = total
        else:
            mem_usage["used"] = 0
            mem_usage["total"] = 0
        return mem_usage

    def disk_usage(self):
        devices = []
        dev_usage = []
        tree = ElementTree.fromstring(self._XMLDesc(0))
        for disk in tree.findall("devices/disk"):
            if disk.get("device") == "disk":
                dev_file = None
                dev_bus = None
                network_disk = True
                for elm in disk:
                    if elm.tag == "source":
                        if elm.get("protocol"):
                            dev_file = elm.get("protocol")
                            network_disk = True
                        if elm.get("file"):
                            dev_file = elm.get("file")
                        if elm.get("dev"):
                            dev_file = elm.get("dev")
                    if elm.tag == "target":
                        dev_bus = elm.get("dev")
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
            dev_usage.append({"dev": dev[1], "rd": rd_diff_usage, "wr": wr_diff_usage})
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
                dev_usage.append({"dev": i, "rx": rx_diff_usage, "tx": tx_diff_usage})
        else:
            for i, dev in enumerate(self.get_net_devices()):
                dev_usage.append({"dev": i, "rx": 0, "tx": 0})
        return dev_usage

    def get_telnet_port(self):
        telnet_port = None
        service_port = None
        tree = ElementTree.fromstring(self._XMLDesc(0))
        for console in tree.findall("devices/console"):
            if console.get("type") == "tcp":
                for elm in console:
                    if elm.tag == "source":
                        if elm.get("service"):
                            service_port = elm.get("service")
                    if elm.tag == "protocol":
                        if elm.get("type") == "telnet":
                            if service_port is not None:
                                telnet_port = service_port
        return telnet_port

    def get_console_listener_addr(self):
        listener_addr = util.get_xml_path(
            self._XMLDesc(0), "/domain/devices/graphics/@listen"
        )
        if listener_addr is None:
            listener_addr = util.get_xml_path(
                self._XMLDesc(0), "/domain/devices/graphics/listen/@address"
            )
            if listener_addr is None:
                return "127.0.0.1"
        return listener_addr

    def set_console_listener_addr(self, listener_addr):
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
        if listener_addr:
            graphic.set("listen", listener_addr)
            listen.set("address", listener_addr)
        else:
            with contextlib.suppress(Exception):
                graphic.attrib.pop("listen")
                listen.attrib.pop("address")

        newxml = ElementTree.tostring(root).decode()
        return self._defineXML(newxml)

    def get_console_socket(self):
        socket = util.get_xml_path(self._XMLDesc(0), "/domain/devices/graphics/@socket")
        return socket

    def get_console_type(self):
        console_type = util.get_xml_path(
            self._XMLDesc(0), "/domain/devices/graphics/@type"
        )
        if console_type is None:
            console_type = util.get_xml_path(
                self._XMLDesc(0), "/domain/devices/console/@type"
            )
        return console_type

    def set_console_type(self, console_type):
        current_type = self.get_console_type()
        if current_type == console_type:
            return True
        if console_type == "":
            return False
        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        root = ElementTree.fromstring(xml)
        try:
            graphic = root.find(f"devices/graphics[@type='{current_type}']")
        except SyntaxError:
            # Little fix for old version ElementTree
            graphic = root.find("devices/graphics")
        graphic.set("type", console_type)
        newxml = ElementTree.tostring(root).decode()
        self._defineXML(newxml)

    def get_console_port(self, console_type=None):
        if console_type is None:
            console_type = self.get_console_type()
        port = util.get_xml_path(
            self._XMLDesc(0),
            "/domain/devices/graphics[@type='%s']/@port" % console_type,
        )
        return port

    def get_console_websocket_port(self):
        console_type = self.get_console_type()
        websocket_port = util.get_xml_path(
            self._XMLDesc(0),
            "/domain/devices/graphics[@type='%s']/@websocket" % console_type,
        )
        return websocket_port

    def get_console_passwd(self):
        return util.get_xml_path(
            self._XMLDesc(VIR_DOMAIN_XML_SECURE), "/domain/devices/graphics/@passwd"
        )

    def set_console_passwd(self, passwd):
        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        root = ElementTree.fromstring(xml)
        console_type = self.get_console_type()
        try:
            graphic = root.find(f"devices/graphics[@type='{console_type}']")
        except SyntaxError:
            # Little fix for old version ElementTree
            graphic = root.find("devices/graphics")
        if graphic is None:
            return False
        if passwd:
            graphic.set("passwd", passwd)
        else:
            with contextlib.suppress(Exception):
                graphic.attrib.pop("passwd")

        newxml = ElementTree.tostring(root).decode()
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
        if keymap != "auto":
            graphic.set("keymap", keymap)
        else:
            with contextlib.suppress(Exception):
                graphic.attrib.pop("keymap")

        newxml = ElementTree.tostring(root).decode()
        self._defineXML(newxml)

    def get_console_keymap(self):
        return (
            util.get_xml_path(
                self._XMLDesc(VIR_DOMAIN_XML_SECURE), "/domain/devices/graphics/@keymap"
            )
            or ""
        )

    def get_video_model(self):
        """:return only primary video card"""
        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        tree = etree.fromstring(xml)
        video_models = tree.xpath("/domain/devices/video/model")
        for model in video_models:
            if model.get("primary") == "yes" or len(video_models) == 1:
                return model.get("type")

    def set_video_model(self, model):
        """Changes only primary video card"""
        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        tree = etree.fromstring(xml)
        video_models = tree.xpath("/domain/devices/video/model")
        video_xml = "<model type='{}'/>".format(model)
        for model in video_models:
            if model.get("primary") == "yes" or len(video_models) == 1:
                parent = model.getparent()
                parent.remove(model)
                parent.append(etree.fromstring(video_xml))
                self._defineXML(etree.tostring(tree).decode())

    def resize_cpu(self, cur_vcpu, vcpu):
        """
        Function change ram and cpu on instance.
        """
        is_vcpus_enabled = self.get_vcpus()
        if is_vcpus_enabled:
            self.set_vcpu_hotplug(False)

        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        tree = etree.fromstring(xml)

        vcpu_elem = tree.find("vcpu")
        vcpu_elem.text = vcpu
        vcpu_elem.set("current", cur_vcpu)

        new_xml = etree.tostring(tree).decode()
        self._defineXML(new_xml)

        if is_vcpus_enabled:
            self.set_vcpu_hotplug(True, int(cur_vcpu))

    def resize_mem(self, cur_memory, memory):
        """
        Function change ram and cpu on vds.
        """
        memory = int(memory) * 1024
        cur_memory = int(cur_memory) * 1024
        # if dom is running change only ram
        if self.get_status() == VIR_DOMAIN_RUNNING:
            self.set_memory(cur_memory, VIR_DOMAIN_AFFECT_LIVE)
            self.set_memory(cur_memory, VIR_DOMAIN_AFFECT_CONFIG)
            return

        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        tree = etree.fromstring(xml)

        mem_elem = tree.find("memory")
        mem_elem.text = str(memory)
        cur_mem_elem = tree.find("currentMemory")
        cur_mem_elem.text = str(cur_memory)

        new_xml = etree.tostring(tree).decode()
        self._defineXML(new_xml)

    def resize_disk(self, disks):
        """
        Function change disks on vds.
        """
        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        tree = etree.fromstring(xml)

        for disk in disks:
            source_dev = disk["path"]
            vol = self.get_volume_by_path(source_dev)
            vol.resize(disk["size_new"])

        new_xml = etree.tostring(tree).decode()
        self._defineXML(new_xml)

    def get_iso_media(self):
        iso = []
        storages = self.get_storages(only_actives=True)
        for storage in storages:
            stg = self.get_storage(storage)
            if stg.info()[0] != 0:
                with contextlib.suppress(Exception):
                    stg.refresh(0)

                for img in stg.listVolumes():
                    if img.lower().endswith(".iso"):
                        iso.append(img)
        return iso

    def delete_all_disks(self):
        self.refresh_instance_pools()
        disks = self.get_disk_devices()
        for disk in disks:
            vol = self.get_volume_by_path(disk.get("path"))
            vol.delete(0)

    def _snapshotCreateXML(self, xml, flag):
        self.instance.snapshotCreateXML(xml, flag)

    def create_snapshot(self, name, desc=None):
        state = "shutoff" if self.get_status() == 5 else "running"
        xml = """<domainsnapshot>
                     <name>%s</name>
                     <description>%s</description>
                     <state>%s</state>
                     <creationTime>%d</creationTime>""" % (
            name,
            desc,
            state,
            time.time(),
        )
        self.change_snapshot_xml()
        xml += self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        xml += """<active>0</active>
                  </domainsnapshot>"""
        self._snapshotCreateXML(xml, 0)
        self.recover_snapshot_xml()

    def change_snapshot_xml(self):
        xml_temp = self._XMLDesc(VIR_DOMAIN_XML_SECURE).replace(
            "<loader readonly='yes' type='pflash'>",
            "<loader readonly='yes' type='rom'>",
        )
        self._defineXML(xml_temp)

    def recover_snapshot_xml(self):
        xml_temp = self._XMLDesc(VIR_DOMAIN_XML_SECURE).replace(
            "<loader readonly='yes' type='rom'>",
            "<loader readonly='yes' type='pflash'>",
        )
        self._defineXML(xml_temp)

    def create_external_snapshot(self, name, date=None, desc=None):
        creation_time = time.time()
        state = "shutoff" if self.get_status() == 5 else "running"
        #<seclabel type='none' model='dac' relabel='no'/>
        xml = """<domainsnapshot>
                     <name>%s</name>
                     <description>%s</description>
                     <state>%s</state>
                     <creationTime>%d</creationTime>
                     """ % (
            name,
            desc,
            state,
            creation_time,
        )

        self.change_snapshot_xml()
        xml += self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        xml += """<active>0</active>
                  </domainsnapshot>"""

        self._snapshotCreateXML(xml, VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY)
        self.refresh_instance_pools()

    def get_external_snapshots(self):
        return self.get_snapshot(VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL)
    
    def delete_external_snapshot(self, name):
        disk_info = self.get_disk_devices()
        for disk in disk_info:
            target_dev = disk["dev"]
            backing_file = disk["backing_file"]
            snap_source_file = disk["path"]
            self.instance.blockCommit(target_dev, backing_file, snap_source_file,
                                                  flags=VIR_DOMAIN_BLOCK_COMMIT_DELETE|
                                                  VIR_DOMAIN_BLOCK_COMMIT_ACTIVE)
            while True:
                info = self.instance.blockJobInfo(target_dev, 0)
                if info.get('cur') == info.get('end'):
                    self.instance.blockJobAbort(target_dev,flags=VIR_DOMAIN_BLOCK_JOB_ABORT_PIVOT)
                    time.sleep(2)
                    break
            # Check again pool for snapshot delta volume; if it exist, remove it manually
            with contextlib.suppress(libvirtError):
                vol_snap = self.get_volume_by_path(snap_source_file)
                pool = vol_snap.storagePoolLookupByVolume()
                pool.refresh(0)
                vol_snap.delete(0)

        snap = self.instance.snapshotLookupByName(name, 0)
        snap.delete(VIR_DOMAIN_SNAPSHOT_DELETE_METADATA_ONLY)

    
    def revert_external_snapshot(self, name, date, desc):
        snap = self.instance.snapshotLookupByName(name, 0)
        snap_xml = snap.getXMLDesc(0)
        snapXML = ElementTree.fromstring(snap_xml)

        self.start(flags=VIR_DOMAIN_START_PAUSED) if self.get_status() == 5 else None
        self.delete_all_disks()
        
        self.force_shutdown()

        snap.delete(VIR_DOMAIN_SNAPSHOT_DELETE_METADATA_ONLY)

        disks = snapXML.findall('inactiveDomain/devices/disk')
        if not disks: disks = snapXML.findall('domain/devices/disk')
        for disk in disks:
            self.instance.updateDeviceFlags(ElementTree.tostring(disk).decode("UTF-8"))
        name = name.replace("s1", "s2")
        self.create_external_snapshot(name, date, desc)

    def get_snapshot(self, flag=VIR_DOMAIN_SNAPSHOT_LIST_INTERNAL):
        snapshots = []
        snapshot_list = self.instance.snapshotListNames(flag)
        for snapshot in snapshot_list:
            snap = self.instance.snapshotLookupByName(snapshot, 0)
            snap_description = util.get_xml_path(
                snap.getXMLDesc(0), "/domainsnapshot/description"
            )
            snap_time_create = util.get_xml_path(
                snap.getXMLDesc(0), "/domainsnapshot/creationTime"
            )
            snapshots.append(
                {
                    "date": datetime.fromtimestamp(int(snap_time_create)),
                    "name": snapshot,
                    "description": snap_description,
                }
            )
        return snapshots

    def snapshot_delete(self, snapshot):
        snap = self.instance.snapshotLookupByName(snapshot, 0)
        snap.delete(0)

    def snapshot_revert(self, snapshot):
        self.change_snapshot_xml()
        snap = self.instance.snapshotLookupByName(snapshot, 0)
        self.instance.revertToSnapshot(snap, 0)
        self.recover_snapshot_xml()

    def get_managed_save_image(self):
        return self.instance.hasManagedSaveImage(0)

    def get_wvmStorage(self, pool):
        return wvmStorage(self.host, self.login, self.passwd, self.conn, pool)

    def get_wvmStorages(self):
        return wvmStorages(self.host, self.login, self.passwd, self.conn)

    def refresh_instance_pools(self):
        disks = self.get_disk_devices()
        target_paths = set()
        for disk in disks:
            disk_path = disk.get("path")
            target_paths.add(os.path.dirname(disk_path))
        for target_path in target_paths:
            self.get_wvmStorages().get_pool_by_target(target_path).refresh(0)

    def fix_mac(self, mac):
        if ":" in mac:
            return mac
        # if mac does not contain ":", try to split into tuples and join with ":"
        n = 2
        mac_tuples = [mac[i : i + n] for i in range(0, len(mac), n)]
        return ":".join(mac_tuples)

    def clone_instance(self, clone_data):
        clone_dev_path = []

        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        tree = etree.fromstring(xml)
        name = tree.find("name")
        name.text = clone_data["name"]
        uuid = tree.find("uuid")
        tree.remove(uuid)

        options = {
            "title": clone_data.get("clone-title", ""),
            "description": clone_data.get("clone-description", ""),
        }
        self._set_options(tree, options)

        src_nvram_path = self.get_nvram()
        if src_nvram_path:
            # Change XML for nvram
            nvram = tree.find("os/nvram")
            nvram.getparent().remove(nvram)

            # NVRAM CLONE: create pool if nvram is not in a pool. then clone it
            src_nvram_name = os.path.basename(src_nvram_path)
            nvram_dir = os.path.dirname(src_nvram_path)
            nvram_pool_name = os.path.basename(nvram_dir)
            try:
                self.get_volume_by_path(src_nvram_path)
            except libvirtError:
                stg_conn = self.get_wvmStorages()
                stg_conn.create_storage("dir", nvram_pool_name, None, nvram_dir)

            new_nvram_name = f"{clone_data['name']}_VARS"
            nvram_stg = self.get_wvmStorage(nvram_pool_name)
            nvram_stg.clone_volume(src_nvram_name, new_nvram_name, file_suffix="fd")

        for num, net in enumerate(tree.findall("devices/interface")):
            elm = net.find("mac")
            mac_address = self.fix_mac(clone_data["clone-net-mac-" + str(num)])
            elm.set("address", mac_address)

        for disk in tree.findall("devices/disk"):
            if disk.get("device") == "disk":
                elm = disk.find("target")
                device_name = elm.get("dev")
                if device_name:
                    target_file = clone_data["disk-" + device_name]
                    meta_prealloc = False
                    with contextlib.suppress(Exception):
                        meta_prealloc = clone_data["meta-" + device_name]

                    elm.set("dev", device_name)

                elm = disk.find("source")
                source_file = elm.get("file")
                if source_file:
                    clone_dev_path.append(source_file)
                    clone_path = os.path.join(os.path.dirname(source_file), target_file)
                    elm.set("file", clone_path)

                    vol = self.get_volume_by_path(source_file)
                    vol_format = util.get_xml_path(
                        vol.XMLDesc(0), "/volume/target/format/@type"
                    )

                    if vol_format == "qcow2" and meta_prealloc:
                        meta_prealloc = True

                    vol_clone_xml = f"""
                                    <volume>
                                        <name>{target_file}</name>
                                        <capacity>0</capacity>
                                        <allocation>0</allocation>
                                        <target>
                                            <format type='{vol_format}'/>
                                            <permissions>
                                                <owner>{clone_data['disk_owner_uid']}</owner>
                                                <group>{clone_data['disk_owner_gid']}</group>
                                                <mode>0644</mode>
                                                <label>virt_image_t</label>
                                            </permissions>
                                            <compat>1.1</compat>
                                            <features>
                                                <lazy_refcounts/>
                                            </features>
                                        </target>
                                    </volume>"""

                    stg = vol.storagePoolLookupByVolume()
                    stg.createXMLFrom(vol_clone_xml, vol, meta_prealloc)

                source_protocol = elm.get("protocol")
                if source_protocol == "rbd":
                    source_name = elm.get("name")
                    clone_name = "%s/%s" % (os.path.dirname(source_name), target_file)
                    elm.set("name", clone_name)

                    vol = self.get_volume_by_path(source_name)
                    vol_format = util.get_xml_path(
                        vol.XMLDesc(0), "/volume/target/format/@type"
                    )

                    vol_clone_xml = f"""
                                    <volume type='network'>
                                        <name>{target_file}</name>
                                        <capacity>0</capacity>
                                        <allocation>0</allocation>
                                        <target>
                                            <format type='{vol_format}'/>
                                        </target>
                                    </volume>"""
                    stg = vol.storagePoolLookupByVolume()
                    stg.createXMLFrom(vol_clone_xml, vol, meta_prealloc)

                source_dev = elm.get("dev")
                if source_dev:
                    clone_path = os.path.join(os.path.dirname(source_dev), target_file)
                    elm.set("dev", clone_path)

                    vol = self.get_volume_by_path(source_dev)
                    stg = vol.storagePoolLookupByVolume()

                    vol_name = util.get_xml_path(vol.XMLDesc(0), "/volume/name")
                    pool_name = util.get_xml_path(stg.XMLDesc(0), "/pool/name")

                    storage = self.get_wvmStorage(pool_name)
                    storage.clone_volume(vol_name, target_file)

        self._defineXML(ElementTree.tostring(tree).decode())

        return self.get_instance(clone_data["name"]).UUIDString()

    def get_bridge_name(self, source, source_type="net"):
        if source_type == "iface":
            iface = self.get_iface(source)
            bridge_name = iface.name()
        else:
            net = self.get_network(source)
            try:
                bridge_name = net.bridgeName()
            except libvirtError:
                bridge_name = None
        return bridge_name

    def add_network(
        self, mac_address, source, source_type="net", model="virtio", nwfilter=None
    ):

        if source_type == "net":
            interface_type = "network"
        elif source_type == "bridge":
            interface_type = "bridge"
        else:
            interface_type = "direct"

        # network modes not handled: default is bridge

        xml_iface = f"""
          <interface type='{interface_type}'>
          <mac address='{mac_address}'/>"""
        if interface_type == "network":
            xml_iface += f"""<source network='{source}'/>"""
        elif interface_type == "direct":
            xml_iface += f"""<source dev='{source}' mode='bridge'/>"""
        elif interface_type == "bridge":
            xml_iface += f"""<source bridge='{source}'/>"""
        else:
            raise libvirtError(f"'{interface_type}' is an unexpected interface type.")
        xml_iface += f"""<model type='{model}'/>"""
        if nwfilter:
            xml_iface += f"""<filterref filter='{nwfilter}'/>"""
        xml_iface += """</interface>"""

        if self.get_status() == 1:
            self.instance.attachDeviceFlags(xml_iface, VIR_DOMAIN_AFFECT_LIVE)
            self.instance.attachDeviceFlags(xml_iface, VIR_DOMAIN_AFFECT_CONFIG)
        if self.get_status() == 5:
            self.instance.attachDeviceFlags(xml_iface, VIR_DOMAIN_AFFECT_CONFIG)

    def delete_network(self, mac_address):
        tree = ElementTree.fromstring(self._XMLDesc(0))
        for interface in tree.findall("devices/interface"):
            source = interface.find("mac")
            if source.get("address", "") == mac_address:
                new_xml = ElementTree.tostring(interface).decode()

                if self.get_status() == 1:
                    self.instance.detachDeviceFlags(new_xml, VIR_DOMAIN_AFFECT_LIVE)
                    self.instance.detachDeviceFlags(new_xml, VIR_DOMAIN_AFFECT_CONFIG)
                if self.get_status() == 5:
                    self.instance.detachDeviceFlags(new_xml, VIR_DOMAIN_AFFECT_CONFIG)
                return new_xml
        return None

    def change_network(self, network_data):
        net_mac = network_data.get("net-mac-0")
        net_source = network_data.get("net-source-0")
        net_source_type = network_data.get("net-source-0-type")
        net_filter = network_data.get("net-nwfilter-0")
        net_model = network_data.get("net-model-0")

        # Remove interface first, but keep network interface XML definition
        # If there is an error happened while adding changed one, then add removed one to back.
        status = self.delete_network(net_mac)
        try:
            self.add_network(
                net_mac, net_source, net_source_type, net_model, net_filter
            )
        except libvirtError:
            if status is not None:
                if self.get_status() == 1:
                    self.instance.attachDeviceFlags(status, VIR_DOMAIN_AFFECT_LIVE)
                    self.instance.attachDeviceFlags(status, VIR_DOMAIN_AFFECT_CONFIG)
                if self.get_status() == 5:
                    self.instance.attachDeviceFlags(status, VIR_DOMAIN_AFFECT_CONFIG)

    def change_network_oldway(self, network_data):
        """
        change network firsh version...
        will be removed if new one works as expected for all scenarios
        """
        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        tree = ElementTree.fromstring(xml)
        for num, interface in enumerate(tree.findall("devices/interface")):
            net_mac = network_data.get("net-mac-" + str(num))
            if net_mac is None:
                continue
            net_source = network_data.get("net-source-" + str(num))
            net_source_type = network_data.get("net-source-" + str(num) + "-type")
            net_filter = network_data.get("net-nwfilter-" + str(num))
            net_model = network_data.get("net-model-" + str(num))

            source = interface.find("source")
            if interface.get("type") == "bridge":
                bridge_name = self.get_bridge_name(net_source, net_source_type)
                source.set("bridge", bridge_name)
            elif interface.get("type") in ["network", "direct"]:
                if net_source_type == "net":
                    source.set("network", net_source)
                elif net_source_type == "iface":
                    source.set("dev", net_source)
                else:
                    raise libvirtError(
                        "Unknown network type: {}".format(net_source_type)
                    )
            else:
                raise libvirtError(
                    "Unknown network type: {}".format(interface.get("type"))
                )

            source = interface.find("model")
            if net_model != "default":
                source.attrib["type"] = net_model
            else:
                interface.remove(source)

            source = interface.find("mac")
            source.set("address", net_mac)
            source = interface.find("filterref")
            if net_filter:
                if source is not None:
                    source.set("filter", net_filter)
                else:
                    element = ElementTree.Element("filterref")
                    element.attrib["filter"] = net_filter
                    interface.append(element)
            else:
                if source is not None:
                    interface.remove(source)

        new_xml = ElementTree.tostring(tree).decode()
        self._defineXML(new_xml)

    def set_link_state(self, mac_address, state):
        tree = etree.fromstring(self._XMLDesc(0))
        for interface in tree.findall("devices/interface"):
            source = interface.find("mac")
            if source.get("address") == mac_address:
                link = interface.find("link")
                if link is not None:
                    interface.remove(link)
                link_el = etree.Element("link")
                link_el.attrib["state"] = state
                interface.append(link_el)
                new_xml = etree.tostring(interface).decode()
                if self.get_status() == 1:
                    self.instance.updateDeviceFlags(new_xml, VIR_DOMAIN_AFFECT_LIVE)
                    self.instance.updateDeviceFlags(new_xml, VIR_DOMAIN_AFFECT_CONFIG)
                if self.get_status() == 5:
                    self.instance.updateDeviceFlags(new_xml, VIR_DOMAIN_AFFECT_CONFIG)

    def _set_options(self, tree, options):
        for o in ["title", "description"]:
            option = tree.find(o)
            option_value = options.get(o, "").strip()
            if not option_value:
                if option is not None:
                    tree.remove(option)
            else:
                if option is None:
                    option = etree.SubElement(tree, o)
                option.text = option_value

    def set_options(self, options):
        """
        Function change description, title
        """
        xml = self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        tree = etree.fromstring(xml)

        self._set_options(tree, options)
        new_xml = etree.tostring(tree).decode()
        self._defineXML(new_xml)

    def set_memory(self, size, flags=0):
        self.instance.setMemoryFlags(size, flags)

    def get_all_qos(self):
        qos_values = dict()
        tree = etree.fromstring(self._XMLDesc(0))
        qos = tree.xpath("/domain/devices/interface")

        for q in qos:
            bound_list = list()
            mac = q.xpath("mac/@address")
            band = q.find("bandwidth")
            if band is not None:
                in_qos = band.find("inbound")
                if in_qos is not None:
                    in_av = in_qos.get("average")
                    in_peak = in_qos.get("peak")
                    in_burst = in_qos.get("burst")
                    in_floor = in_qos.get("floor")
                    bound_list.append(
                        {
                            "direction": "inbound",
                            "average": in_av,
                            "peak": in_peak,
                            "floor": in_floor,
                            "burst": in_burst,
                        }
                    )

                out_qos = band.find("outbound")
                if out_qos is not None:
                    out_av = out_qos.get("average")
                    out_peak = out_qos.get("peak")
                    out_burst = out_qos.get("burst")
                    bound_list.append(
                        {
                            "direction": "outbound",
                            "average": out_av,
                            "peak": out_peak,
                            "burst": out_burst,
                        }
                    )
                qos_values[mac[0]] = bound_list
        return qos_values

    def set_qos(self, mac, direction, average, peak, burst):
        if direction == "inbound":
            xml = f"<inbound average='{average}' peak='{peak}' burst='{burst}'/>"
        elif direction == "outbound":
            xml = f"<outbound average='{average}' peak='{peak}' burst='{burst}'/>"
        else:
            raise Exception("Direction must be inbound or outbound")

        tree = etree.fromstring(self._XMLDesc(0))

        macs = tree.xpath("/domain/devices/interface/mac")
        for cur_mac in macs:

            if cur_mac.get("address") == mac:
                interface = cur_mac.getparent()
                band = interface.find("bandwidth")
                if band is None:
                    xml = "<bandwidth>" + xml + "</bandwidth>"
                    interface.append(etree.fromstring(xml))
                else:
                    direct = band.find(direction)
                    if direct is not None:
                        parent = direct.getparent()
                        parent.remove(direct)
                        parent.append(etree.fromstring(xml))
                    else:
                        band.append(etree.fromstring(xml))
        new_xml = etree.tostring(tree).decode()
        self.wvm.defineXML(new_xml)

    def unset_qos(self, mac, direction):
        tree = etree.fromstring(self._XMLDesc(0))
        for direct in tree.xpath(
            "/domain/devices/interface/bandwidth/{}".format(direction)
        ):
            band_el = direct.getparent()
            interface_el = (
                band_el.getparent()
            )  # parent bandwidth,its parent is interface
            parent_mac = interface_el.xpath("mac/@address")
            if parent_mac[0] == mac:
                band_el.remove(direct)

        self.wvm.defineXML(etree.tostring(tree).decode())

    def add_guest_agent(self):
        channel_xml = """
                        <channel type='unix'>
                            <target type='virtio' name='org.qemu.guest_agent.0'/>
                        </channel>
                      """
        if self.get_status() == 1:
            self.instance.attachDeviceFlags(channel_xml, VIR_DOMAIN_AFFECT_LIVE)
            self.instance.attachDeviceFlags(channel_xml, VIR_DOMAIN_AFFECT_CONFIG)
        if self.get_status() == 5:
            self.instance.attachDeviceFlags(channel_xml, VIR_DOMAIN_AFFECT_CONFIG)

    def remove_guest_agent(self):
        tree = etree.fromstring(self._XMLDesc(0))
        for target in tree.xpath(
            "/domain/devices/channel[@type='unix']/target[@name='org.qemu.guest_agent.0']"
        ):
            parent = target.getparent()
            channel_xml = etree.tostring(parent).decode()
            if self.get_status() == 1:
                self.instance.detachDeviceFlags(channel_xml, VIR_DOMAIN_AFFECT_LIVE)
                self.instance.detachDeviceFlags(channel_xml, VIR_DOMAIN_AFFECT_CONFIG)
            if self.get_status() == 5:
                self.instance.detachDeviceFlags(channel_xml, VIR_DOMAIN_AFFECT_CONFIG)

    def get_guest_agent(self):
        def _get_agent(doc):
            """
            Return agent channel object if it is defined.
            """
            for channel in doc.xpath("/domain/devices/channel"):
                ch_type = channel.get("type")
                target = channel.find("target")
                target_name = target.get("name")
                if ch_type == "unix" and target_name == "org.qemu.guest_agent.0":
                    return channel
            return None

        return util.get_xml_path(self._XMLDesc(0), func=_get_agent)

    def is_agent_ready(self):
        """
        Return connected state of an agent.
        """
        # we need to get a fresh agent channel object on each call so it
        # reflects the current state
        dev = self.get_guest_agent()
        if dev is not None:
            states = dev.xpath("target/@state")
            state = states[0] if len(states) > 0 else ""
            if state == "connected":
                return True
            return False
