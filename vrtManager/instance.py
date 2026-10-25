import base64
import contextlib
import io
import ipaddress
import json
import logging
import os.path
import re
import string
import time

logger = logging.getLogger(__name__)

try:
    from libvirt import (
        VIR_DOMAIN_AFFECT_CONFIG,
        VIR_DOMAIN_AFFECT_LIVE,
        VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP,
        VIR_DOMAIN_XML_SECURE,
        VIR_DOMAIN_XML_INACTIVE,
        VIR_DOMAIN_XML_MIGRATABLE,
        VIR_DOMAIN_UNDEFINE_KEEP_NVRAM,
        VIR_ERR_NO_DOMAIN,
        VIR_ERR_NO_STORAGE_POOL,
        VIR_ERR_NO_STORAGE_VOL,
        VIR_CONNECT_LIST_STORAGE_POOLS_ACTIVE,
        VIR_DOMAIN_BLOCK_RESIZE_BYTES,
        VIR_STORAGE_VOL_FILE,
        VIR_MIGRATE_AUTO_CONVERGE,
        VIR_MIGRATE_COMPRESSED,
        VIR_MIGRATE_LIVE,
        VIR_MIGRATE_OFFLINE,
        VIR_MIGRATE_PERSIST_DEST,
        VIR_MIGRATE_UNDEFINE_SOURCE,
        VIR_MIGRATE_UNSAFE,
        VIR_DOMAIN_SNAPSHOT_CREATE_ATOMIC,
        VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY,
        VIR_DOMAIN_SNAPSHOT_CREATE_QUIESCE,
        VIR_DOMAIN_SNAPSHOT_REVERT_PAUSED,
        VIR_DOMAIN_SNAPSHOT_REVERT_RUNNING,
        VIR_ERR_CONFIG_UNSUPPORTED,
        VIR_ERR_OPERATION_INVALID,
        VIR_DOMAIN_SNAPSHOT_LIST_INTERNAL,
        VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL,
        VIR_DOMAIN_BACKUP_BEGIN_REUSE_EXTERNAL,
        VIR_DOMAIN_JOB_NONE,
        VIR_DOMAIN_JOB_OPERATION_BACKUP,
        VIR_DOMAIN_JOB_STATS_COMPLETED,
        VIR_DOMAIN_JOB_STATS_KEEP_COMPLETED,
        VIR_ERR_NO_DOMAIN_BACKUP,
        libvirtError,
    )
    from libvirt_qemu import qemuAgentCommand
except Exception:
    from libvirt import libvirtError, VIR_DOMAIN_XML_SECURE, VIR_DOMAIN_XML_INACTIVE, VIR_MIGRATE_LIVE

from collections import OrderedDict
from datetime import datetime
from xml.etree import ElementTree

from lxml import etree

from vrtManager import util
from vrtManager.connection import NVRAM_DIR, wvmConnect
from vrtManager.storage import wvmStorage, wvmStorages

# Edits that redefine the domain start from this: the persistent definition,
# with secrets. Live XML would drop pending changes, non-secure XML the VNC
# password.
PERSISTENT_XML = VIR_DOMAIN_XML_INACTIVE | VIR_DOMAIN_XML_SECURE

# External snapshot names become part of overlay and memory file names.
SNAPSHOT_NAME = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}")
# the longest window wvmInstance.usage() averages over
USAGE_MAX_WINDOW = 30
# seconds the guest agent has to set a password or add a key
AGENT_TIMEOUT = 10
# A running VM is cloned with a push backup that keeps the VM alive when the
# guest shuts down during the copy: libvirt 11.10.
LIVE_CLONE_MIN_LIBVIRT = 11_010_000
# libvirt 11.10's value; bindings built against older libvirt lack the name,
# and the flag is sent to the host, whose version is checked.
VIR_DOMAIN_BACKUP_BEGIN_PRESERVE_SHUTDOWN_DOMAIN = 2


def _rate(before, after, seconds, scale=1):
    """Growth per second of a counter, or None when a reading is unsupported
    (-1) or the counter went back."""
    if before < 0 or after < before:
        return None
    return scale * (after - before) / seconds


class wvmInstances(wvmConnect):
    def moveto(self, conn, name, live, unsafe, offline, autoconverge=False, compress=False, uri=None):
        """Migrates the VM of conn (a wvmInstance on the source) here.

        The mode follows the VM's state, read once: a running VM migrates
        live or, without live, paused for the transfer (non-live); a paused
        VM stays paused; a shut-off VM moves offline. A request that does not
        fit the state is refused. unsafe, autoconverge (live only) and
        compress apply to a running VM. uri: the native migration URI
        (tcp://address) on the destination; None lets libvirt use the
        destination's own hostname. Returns the mode and options used, for
        the log."""
        state = conn.get_status()
        if state == 5:
            if live:
                raise util.OperationError("A shut-off VM cannot be migrated live")
            mode = ["offline"]
        elif state in (1, 3):
            if offline:
                raise util.OperationError("A running or paused VM cannot be migrated offline")
            mode = ["live" if live else "non-live"]
        else:
            raise util.OperationError("The VM can be migrated when it is running, paused or shut off")

        # The source definition always goes: one left behind points at the
        # same (shared) disks as the migrated VM and could be started again.
        flags = VIR_MIGRATE_PERSIST_DEST | VIR_MIGRATE_UNDEFINE_SOURCE
        if state == 5:
            flags |= VIR_MIGRATE_OFFLINE
        elif live:
            flags |= VIR_MIGRATE_LIVE
        if state == 1:
            for wanted, flag, label in (
                (unsafe, VIR_MIGRATE_UNSAFE, "unsafe"),
                (autoconverge and live, VIR_MIGRATE_AUTO_CONVERGE, "auto converge"),
                (compress, VIR_MIGRATE_COMPRESSED, "compressed"),
            ):
                if wanted:
                    flags |= flag
                    mode.append(label)

        dom = conn.instance
        # libvirt keeps snapshot metadata on the source host: shared disks do
        # not carry it to the destination.
        if dom.snapshotNum(0):
            raise util.OperationError("A VM with snapshots cannot be migrated")
        if state == 5:
            self.refuse_local_state(dom.XMLDesc(0))
        definitions = {dom.XMLDesc(0)}
        if state != 5:
            definitions.add(dom.XMLDesc(VIR_DOMAIN_XML_INACTIVE))
        missing = self.missing_disks(definitions)
        if missing:
            raise util.OperationError(
                "The destination host does not have these disks of the VM: "
                + ", ".join(f"{target} ({source})" for target, source in missing)
            )

        dom_arch = conn.get_arch()
        dom_emulator = conn.get_dom_emulator()

        if dom_emulator != self.get_emulator(dom_arch):
            raise util.OperationError(
                "Destination host emulator is different. Cannot be migrated"
            )

        if state == 5:
            # Workaround for a libvirt bug (RHEL-156800), see move_definition.
            # Once supported hosts all run a fixed libvirt, this branch and
            # move_definition can go: the flags above are those for
            # dom.migrate.
            self.move_definition(dom, conn)
        else:
            dom.migrate(self.wvm, flags, None, uri, 0)
        return ", ".join(mode)

    @staticmethod
    def refuse_local_state(xml):
        """A shut-off VM moves without its TPM state, a file of the source
        host: on the destination it would get a new TPM that no longer
        unlocks its disks. A live migration carries it. (The UEFI variables
        are copied: copy_nvram.)"""
        if ElementTree.fromstring(xml).find("devices/tpm/backend[@type='emulator']") is not None:
            raise util.OperationError(
                "A shut-off VM with TPM state cannot be migrated: the state stays on the source host. "
                "Start the VM and migrate it live."
            )

    def copy_nvram(self, conn):
        """Copies the UEFI variables file of the shut-off VM of conn (on the
        source) from libvirt's NVRAM directory there to the same path here,
        unless both hosts share that directory. Returns the copy's name."""
        path = conn.get_nvram()
        if not path or os.path.dirname(path) != NVRAM_DIR:
            return None
        name = os.path.basename(path)
        with conn._nvram_pool() as source, self._nvram_pool() as target:
            vol = self._find_volume(source, name)
            if vol is None:
                return None  # never started: libvirt creates it at the first start
            if self._nvram_shared(source, target):
                if self._find_volume(target, name) is None:
                    raise util.OperationError(f"The destination host cannot see the NVRAM file {path}")
                return None
            chunks = []
            stream = conn.wvm.newStream(0)
            vol.download(stream, 0, 0, 0)
            stream.recvAll(lambda _stream, data, out: out.append(data), chunks)
            stream.finish()
            data = b"".join(chunks)
            copy = target.createXML(
                f"<volume><name>{util.xml_escape(name)}</name><capacity>{len(data)}</capacity>"
                "<target><format type='raw'/></target></volume>",
                0,
            )
            try:
                stream = self.wvm.newStream(0)
                copy.upload(stream, 0, len(data), 0)
                stream.sendAll(lambda _stream, size, buffer: buffer.read(size), io.BytesIO(data))
                stream.finish()
            except Exception:
                copy.delete(0)
                raise
        return name

    def delete_nvram(self, name):
        if name:
            with self._nvram_pool() as pool:
                pool.storageVolLookupByName(name).delete(0)

    def missing_disks(self, definitions):
        """(target, source) of the disks in the VM definitions (XML) that are
        not volumes of this host's active storage pools: the VM's own files,
        their backing files (as the definition or this host's volume lists
        them), CD-ROM images, block devices and pool volumes. Network disks
        (RBD, iSCSI, ...) are reached the same way from every host and are not
        checked; other types (dir, nvme, ...) cannot be and count as missing.
        Pools are refreshed before a disk counts as missing, as a file another
        host made on shared storage is listed after that."""
        disks = {}
        for xml in definitions:
            for disk in ElementTree.fromstring(xml).iter("disk"):
                target = disk.find("target")
                target = target.get("dev") if target is not None else "?"
                for element in (disk, *disk.iter("backingStore")):
                    source = element.find("source")
                    kind = element.get("type")
                    if source is None or kind == "network":
                        continue
                    if kind == "volume":
                        disks[(source.get("pool"), source.get("volume"))] = target
                    elif kind in ("file", "block") and (source.get("file") or source.get("dev")):
                        disks[(None, source.get("file") or source.get("dev"))] = target
                    elif kind not in ("file", "block"):
                        disks[(kind, None)] = target

        def missing():
            checked, unseen, queue = set(), [], list(disks.items())
            while queue:
                key, target = queue.pop()
                if key in checked:
                    continue
                checked.add(key)
                volume = self.find_volume(*key)
                if volume is None:
                    unseen.append((target, key))
                    continue
                backing = ElementTree.fromstring(volume.XMLDesc(0)).findtext("backingStore/path")
                if backing and "://" not in backing:  # a URI is a network backing image
                    queue.append(((None, backing), target))
            return unseen

        if missing():
            for pool in self.wvm.listAllStoragePools(VIR_CONNECT_LIST_STORAGE_POOLS_ACTIVE):
                with contextlib.suppress(libvirtError):
                    pool.refresh(0)
        return [(target, self.disk_label(*key)) for target, key in missing()]

    @staticmethod
    def disk_label(pool, name):
        if name is None:
            return f"{pool} disk, cannot be checked"
        return name if pool is None else f"{pool}/{name}"

    def find_volume(self, pool, name):
        """The volume name of pool, or with pool None the volume at path name;
        None when this host has none (or name is None: a disk type that
        cannot be checked)."""
        if name is None:
            return None
        try:
            if pool is None:
                return self.wvm.storageVolLookupByPath(name)
            pool = self.wvm.storagePoolLookupByName(pool)
            return pool.storageVolLookupByName(name) if pool.isActive() else None
        except libvirtError as error:
            if error.get_error_code() in (VIR_ERR_NO_STORAGE_VOL, VIR_ERR_NO_STORAGE_POOL):
                return None
            raise

    def move_definition(self, dom, conn):
        """Migrates a shut-off VM: that is only its definition, as the disks
        are on storage both hosts share, and its UEFI variables file
        (copy_nvram; moveto refuses a VM with TPM state). The destination's
        qemu migration hook does not run for it.

        Workaround, to be removed in a later version: libvirt's own offline
        migration (VIR_MIGRATE_OFFLINE) fails with "operation failed: domain
        is no longer running" on libvirt builds that have upstream commit
        a4f610ff ("Always offer block dirty bitmaps during migration") but not
        its fix 59fde80f, which is in libvirt 12.2.0. RHEL backported the
        first (RHEL-145770) and tracks the fix as RHEL-156800; RHEL/Rocky 9.8
        with libvirt 11.10.0-12.el9_8 is affected. When supported hosts all
        have the fix, offline migration can go back to dom.migrate."""
        if dom.hasManagedSaveImage(0):
            raise util.OperationError("A VM with a saved state cannot be migrated")
        for lookup, key in ((self.wvm.lookupByUUIDString, dom.UUIDString()), (self.wvm.lookupByName, dom.name())):
            try:
                lookup(key)
            except libvirtError as error:
                if error.get_error_code() != VIR_ERR_NO_DOMAIN:
                    raise
            else:
                raise util.OperationError(f"The destination host already has a VM {key}")

        xml = dom.XMLDesc(VIR_DOMAIN_XML_SECURE | VIR_DOMAIN_XML_MIGRATABLE)
        autostart = dom.autostart()
        nvram = self.copy_nvram(conn)
        try:
            new = self.wvm.defineXML(xml)
        except Exception:
            self.delete_nvram(nvram)
            raise
        try:
            # libvirt refuses to undefine a VM with NVRAM without this; the file stays for the cleanup
            dom.undefineFlags(VIR_DOMAIN_UNDEFINE_KEEP_NVRAM)
            try:
                started = dom.isActive()
            except libvirtError as error:
                if error.get_error_code() != VIR_ERR_NO_DOMAIN:
                    raise
                started = False  # gone from the source: the move is done
            if started:
                # started meanwhile by another client: it stays on the source
                dom.connect().defineXML(xml).setAutostart(autostart)
                raise util.OperationError("The VM was started on the source host during the migration")
        except Exception as error:
            self.undo_definition(dom, new, error)  # raises when the destination keeps the VM
            self.delete_nvram(nvram)
            raise

    @staticmethod
    def undo_definition(dom, new, error):
        """After a failed move, the VM is defined on one host only: the
        destination definition goes only while the source still has its own."""
        try:
            on_source = dom.isPersistent()
        except libvirtError:
            on_source = False
        if not on_source:
            raise util.OperationError(
                f"{error}; the VM may now be defined only on the destination host: check both hosts"
            ) from error
        try:
            new.undefineFlags(VIR_DOMAIN_UNDEFINE_KEEP_NVRAM)
        except libvirtError as undo_error:
            raise util.OperationError(
                f"{error}; the VM is now defined on both hosts, remove it from the destination: {undo_error}"
            ) from error


def agent_command(dom, command, arguments=None):
    """The answer of one guest agent command that waits AGENT_TIMEOUT seconds
    at most: libvirt's own calls for it wait for a hung agent indefinitely,
    and the domain's agent timeout is shared by every agent call."""
    request = {"execute": command}
    if arguments is not None:
        request["arguments"] = arguments
    return json.loads(qemuAgentCommand(dom, json.dumps(request), AGENT_TIMEOUT, 0))["return"]


def agent_interfaces(dom):
    """The guest's interfaces from its agent, in interfaceAddresses()'s form,
    which waits for a hung agent indefinitely."""
    interfaces = {}
    for iface in agent_command(dom, "guest-network-get-interfaces"):
        addrs = []
        for address in iface.get("ip-addresses", []):
            kind = 0 if address["ip-address-type"] == "ipv4" else 1
            addrs.append({"type": kind, "addr": address["ip-address"], "prefix": address["prefix"]})
        interfaces[iface["name"]] = {"hwaddr": iface.get("hardware-address"), "addrs": addrs}
    return interfaces


class wvmInstance(wvmConnect):
    # set by cached_reads(): libvirt answers reused within the block
    _read_cache = None

    def __init__(self, host, login, passwd, conn, vname, uuid=None):
        wvmConnect.__init__(self, host, login, passwd, conn)
        self._ip_cache = None
        # A known VM is found by UUID: a name can be renamed or swapped
        # outside WebVirtCloud. No fallback to the name.
        self.instance = self.wvm.lookupByUUIDString(uuid) if uuid else self.get_instance(vname)

    def osinfo(self):
        info = agent_command(self.instance, "guest-get-osinfo")
        info.update(agent_command(self.instance, "guest-get-timezone"))
        info.update(agent_command(self.instance, "guest-get-host-name"))
        return info

    def start(self, flags=0):
        self.instance.createWithFlags(flags)

    def shutdown(self):
        self.instance.shutdown()

    def force_shutdown(self):
        self.instance.destroy()

    def suspend(self):
        self.instance.suspend()

    def resume(self):
        self.instance.resume()

    def delete(self, flags=0):
        self.instance.undefineFlags(flags)

    @contextlib.contextmanager
    def cached_reads(self):
        """
        Within the block the domain XML (per flags value), the VM's state and
        each disk's volume are read from libvirt once (the host's info and
        capabilities are read once per object anyway), for pages that only
        read: a VM page reads the XML in some 30 getters and each disk in two
        lists. Code that changes the VM must not run inside: most changes
        (devices, QoS, memory) do not go through _defineXML, the only call
        that drops the cache.
        """
        if self._read_cache is not None:
            raise RuntimeError("cached_reads blocks do not nest")
        self._read_cache = {}
        try:
            yield self
        finally:
            self._read_cache = None

    def _cached(self, key, read):
        cache = self._read_cache
        if cache is None:
            return read()
        if key not in cache:
            cache[key] = read()
        return cache[key]

    def _XMLDesc(self, flag):
        return self._cached(("xml", flag), lambda: self.instance.XMLDesc(flag))

    def _defineXML(self, xml):
        if self._read_cache is not None:
            self._read_cache.clear()
        return self.wvm.defineXML(xml)

    def get_status(self):
        """
        VIR_DOMAIN_NOSTATE = 0
        VIR_DOMAIN_RUNNING = 1
        VIR_DOMAIN_PAUSED = 3
        VIR_DOMAIN_SHUTOFF = 5
        """
        return self._cached("status", lambda: self.instance.info()[0])

    def get_autostart(self):
        return self.instance.autostart()

    def set_autostart(self, flag):
        return self.instance.setAutostart(flag)

    def get_uuid(self):
        return self.instance.UUIDString()

    def get_vcpu(self, config=False):
        vcpu = util.get_xml_path(self._XMLDesc(PERSISTENT_XML if config else 0), "/domain/vcpu")
        return int(vcpu)

    def get_cur_vcpu(self, config=False):
        cur_vcpu = util.get_xml_path(self._XMLDesc(PERSISTENT_XML if config else 0), "/domain/vcpu/@current")
        return int(cur_vcpu) if cur_vcpu else self.get_vcpu(config)

    def get_arch(self):
        return util.get_xml_path(self._XMLDesc(0), "/domain/os/type/@arch")

    def get_machine_type(self):
        return util.get_xml_path(self._XMLDesc(0), "/domain/os/type/@machine")

    def get_dom_emulator(self):
        return util.get_xml_path(self._XMLDesc(0), "/domain/devices/emulator")

    def get_nvram(self):
        xml = self._XMLDesc(0)  # a path as text, or a <source file=...> since libvirt 8.5
        return util.get_xml_path(xml, "/domain/os/nvram/source/@file") or util.get_xml_path(xml, "/domain/os/nvram")

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

    def get_title(self, config=False):
        title = util.get_xml_path(self._XMLDesc(PERSISTENT_XML if config else 0), "/domain/title")
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

    def get_description(self, config=False):
        description = util.get_xml_path(self._XMLDesc(PERSISTENT_XML if config else 0), "/domain/description")
        return description or ""

    def get_max_memory(self):
        return self.host_info[1] * 1048576

    def get_max_cpus(self):
        """Get number of physical CPUs."""
        hostinfo = self.host_info
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
            with contextlib.suppress(libvirtError):
                self._ip_cache["qemuga"] = agent_interfaces(self.instance)

        self._ip_cache["arp"] = self._get_interface_addresses(VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP)

    def get_net_devices(self, config=False):
        def networks(ctx):
            result = []
            for net in ctx.xpath("/domain/devices/interface"):
                inbound = outbound = []
                interface_type = net.xpath("@type")[0]
                mac_inst = net.xpath("mac/@address")[0]
                source = net.xpath("source/@network|source/@bridge|source/@dev")
                nic_inst = source[0] if source else ""
                target_inst = net.xpath("target/@dev")[0] if net.xpath("target/@dev") else ""
                link_state = net.xpath("link/@state")[0] if net.xpath("link") else "up"
                filterref_inst = net.xpath("filterref/@filter")[0] if net.xpath("filterref/@filter") else ""

                model_type = net.xpath("model/@type")[0] if net.xpath("model/@type") else ""
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

        return util.get_xml_path(self._XMLDesc(PERSISTENT_XML if config else 0), func=networks)

    def get_disk_devices(self, config=False):
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

                        details = self._volume_details(src_file)
                        if details:
                            volume, disk_size, used_size, storage = details
                        else:
                            volume = src_file
                    except Exception as e:
                        logger.warning("Disk %s of %s not fully read: %s", dev, self.instance.name(), e)
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

        flags = VIR_DOMAIN_XML_INACTIVE | VIR_DOMAIN_XML_SECURE if config else 0
        return util.get_xml_path(self._XMLDesc(flags), func=disks)

    def _volume_details(self, path):
        """(name, capacity, allocation, pool name) of the volume at path, or
        None when no pool holds it."""

        def read():
            try:
                vol = self.get_volume_by_path(path)
                info = vol.info()
                return vol.name(), info[1], info[2], vol.storagePoolLookupByVolume().name()
            except libvirtError:
                return None

        return self._cached(("volume", path), read)

    def get_media_devices(self, config=False):
        def disks(doc):
            result = []
            for media in doc.xpath("/domain/devices/disk[@device='cdrom']"):
                dev = media.xpath("target/@dev")
                bus = media.xpath("target/@bus")
                src_file = media.xpath("source/@file")
                src_file = src_file[0] if src_file else None
                details = self._volume_details(src_file) if src_file else None
                volume, _, _, storage = details or (None, None, None, None)
                result.append(
                    {
                        "dev": dev[0] if dev else None,
                        "image": volume,
                        "storage": storage,
                        "path": src_file,
                        "bus": bus[0] if bus else None,
                    }
                )
            return result

        return util.get_xml_path(self._XMLDesc(PERSISTENT_XML if config else 0), func=disks)

    def get_bootmenu(self, config=False):
        menu = util.get_xml_path(self._XMLDesc(PERSISTENT_XML if config else 0), "/domain/os/bootmenu/@enable")
        return menu == "yes"

    def set_bootmenu(self, flag):
        tree = etree.fromstring(self._XMLDesc(PERSISTENT_XML))
        os = tree.find("os")
        menu = os.find("bootmenu")

        if menu is None:
            bootmenu = etree.fromstring("<bootmenu enable='yes'/>")
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

        xmldom = etree.tostring(tree).decode()
        self._defineXML(xmldom)

    def get_bootorder(self, config=False):
        boot_order = {}
        dev_type = target = None
        tree = ElementTree.fromstring(self._XMLDesc(PERSISTENT_XML if config else 0))
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

                if dev.tag == "disk":  # file, block, volume or network
                    dev_target = dev.find("target").get("dev")

                elif dev.tag == "interface":  # network, bridge or direct
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
            tree = etree.fromstring(self._XMLDesc(PERSISTENT_XML))
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
            order = etree.fromstring("<boot order='{}'/>".format(idx + 1))
            if dev["type"] in ("disk", "cdrom"):
                devices = tree.xpath("./devices/disk[@device=$device][target/@dev=$dev]", device=dev["type"], dev=dev["dev"])
            elif dev["type"] == "network":  # any NIC type: network, bridge, direct
                devices = tree.xpath("./devices/interface[mac/@address=$mac]", mac=dev["dev"])
            else:
                raise util.OperationError("Invalid Device Type for boot order")
            # nothing is defined until every choice is found: the order above is cleared
            if not devices:
                raise util.OperationError(f"Boot device {dev['dev']} is not in the definition")
            for d in devices:
                d.append(order)
        self._defineXML(etree.tostring(tree).decode())

    def _set_cdrom_media(self, dev, path):
        """Insert path into, or with None eject, CD-ROM dev.

        The live and the persistent definition are updated separately from
        their own device XML, so neither is rewritten from the other.
        """
        definitions = [
            ("running" if affect == VIR_DOMAIN_AFFECT_LIVE else "persistent", xml_flags, affect)
            for xml_flags, affect in self._definitions()
        ]
        devices = []
        for label, xml_flags, _ in definitions:
            tree = etree.fromstring(self._XMLDesc(xml_flags))
            found = tree.xpath("./devices/disk[@device='cdrom'][target/@dev=$dev]", dev=dev)
            if not found:
                raise util.OperationError(f"CD-ROM {dev} is not in the {label} definition")
            devices.append(found[0])
        for (label, _, affect), disk in zip(definitions, devices):
            for source in disk.findall("source"):
                disk.remove(source)
            if path:
                disk.insert(1, etree.Element("source", file=path))
            try:
                self.instance.updateDeviceFlags(etree.tostring(disk).decode(), affect)
            except libvirtError as err:
                if label == "persistent" and len(definitions) == 2:
                    raise util.OperationError(f"Media of {dev} changed in the running VM only: {err}") from err
                raise

    def mount_iso(self, dev, image):
        paths = []
        for storage in self.get_storages(only_actives=True):
            stg = self.get_storage(storage)
            if image in stg.listVolumes():
                paths.append(stg.storageVolLookupByName(image).path())
        if not paths:
            raise util.OperationError(f"ISO image {image} was not found")
        if len(paths) > 1:
            raise util.OperationError(f"ISO image {image} is in more than one storage pool")
        self._set_cdrom_media(dev, paths[0])

    def umount_iso(self, dev, image=None):
        self._set_cdrom_media(dev, None)

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
        # Every value below is interpolated into disk XML; escape them all so
        # a quote in a path, serial or option cannot inject XML.
        esc = util.xml_escape
        target_dev, source, target_bus = esc(target_dev), esc(source), esc(target_bus)
        disk_type, disk_device = esc(disk_type), esc(disk_device)
        driver_name, format_type = esc(driver_name), esc(format_type)
        serial = esc(serial)
        cache_mode, io_mode = esc(cache_mode), esc(io_mode)
        discard_mode, detect_zeroes_mode = esc(discard_mode), esc(detect_zeroes_mode)

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
        elif disk_type == "block":  # a volume of an LVM, disk or iSCSI pool
            xml_disk += f"<source dev='{source}'/>"
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
        self._attach_device(xml_disk)

    def detach_disk(self, target_dev):
        """Detach target_dev from each definition that has it, as that definition describes it."""
        found = False
        for xml_flags, affect in self._definitions():
            tree = etree.fromstring(self._XMLDesc(xml_flags))
            disks = tree.xpath("./devices/disk[target/@dev=$dev]", dev=target_dev)
            if disks:
                found = True
                self.instance.detachDeviceFlags(etree.tostring(disks[0]).decode(), affect)
        if not found:
            raise util.OperationError(f"Disk {target_dev} is not in the VM's definition")

    def has_disk(self, target_dev):
        """True while the live or the persistent definition still has target_dev."""
        for flags in (0, VIR_DOMAIN_XML_INACTIVE):
            tree = etree.fromstring(self._XMLDesc(flags))
            if tree.xpath("./devices/disk/target[@dev=$dev]", dev=target_dev):
                return True
        return False

    def wait_disk_detached(self, target_dev, timeout=10):
        """A live detach completes only when the guest releases the disk."""
        deadline = time.monotonic() + timeout
        while self.has_disk(target_dev):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.5)
        return True

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
        """Edit the persistent disk in place and commit its domain XML once."""
        tree = etree.fromstring(
            self._XMLDesc(VIR_DOMAIN_XML_INACTIVE | VIR_DOMAIN_XML_SECURE)
        )
        matches = tree.xpath("./devices/disk/target[@dev=$dev]", dev=target_dev)
        if not matches:
            raise ValueError(f"Disk {target_dev} is not in the persistent configuration")
        target = matches[0]
        disk = target.getparent()

        if target.get("bus") != target_bus:
            prefix = util.vol_dev_type(target_bus) or "sd"
            used = set(tree.xpath("./devices/disk/target/@dev")) - {target_dev}
            new_dev = target_dev if target_dev.startswith(prefix) else next(
                (prefix + letter for letter in string.ascii_lowercase if prefix + letter not in used),
                None,
            )
            if new_dev is None:
                raise ValueError("No available device name for the requested disk bus")
            target.set("dev", new_dev)
            target.set("bus", target_bus)
            for address in disk.findall("address"):
                disk.remove(address)

        driver = disk.find("driver")
        if driver is None:
            driver = etree.Element("driver", name="qemu")
            disk.insert(0, driver)
        if target_bus != "virtio":
            for key in ("queues", "queue_size", "iothread", "iommu", "ats", "packed", "page_per_vq"):
                driver.attrib.pop(key, None)
            for iothreads in driver.findall("iothreads"):
                driver.remove(iothreads)
            disk.attrib.pop("model", None)
        for key, value in (
            ("type", format), ("cache", cache_mode), ("io", io_mode),
            ("discard", discard_mode), ("detect_zeroes", detect_zeroes_mode),
        ):
            if value and value != "default":
                driver.set(key, value)
            else:
                driver.attrib.pop(key, None)

        if disk.get("type") == "file":
            source_el = disk.find("source")
            if source_el is None:
                source_el = etree.SubElement(disk, "source")
            source_el.set("file", source)

        for tag, enabled in (("readonly", readonly), ("shareable", shareable)):
            element = disk.find(tag)
            if enabled and element is None:
                etree.SubElement(disk, tag)
            elif not enabled and element is not None:
                disk.remove(element)
        serial_el = disk.find("serial")
        if serial and serial != "None":
            if serial_el is None:
                serial_el = etree.SubElement(disk, "serial")
            serial_el.text = serial
        elif serial_el is not None:
            disk.remove(serial_el)

        self._defineXML(etree.tostring(tree).decode())

    def set_vcpu(self, cpu_id, enabled):
        self.instance.setVcpu(str(cpu_id), enabled)

    def set_vcpu_hotplug(self, status, vcpus_hotplug=0):
        """vcpus_hotplug: the vCPUs enabled at boot, 0 keeps the current ones;
        libvirt adds the rest up to the maximum as disabled hotpluggable vCPUs"""
        vcpus_hotplug = self.get_cur_vcpu() if vcpus_hotplug == 0 else vcpus_hotplug
        if self.get_status() == 5:  # shutoff
            if status:
                xml = """ <vcpus>"""
                xml += """<vcpu id='0' enabled='yes' hotpluggable='no' order='1'/>"""
                for i in range(1, vcpus_hotplug):
                    xml += f"""<vcpu id='{i}' enabled='yes' hotpluggable='yes' order='{i+1}'/>"""
                xml += """</vcpus>"""

                tree = etree.fromstring(self._XMLDesc(PERSISTENT_XML))
                vcpus = tree.xpath("/domain/vcpus")
                if not vcpus:
                    tree.append(etree.fromstring(xml))
                    self._defineXML(etree.tostring(tree).decode())
            else:
                tree = etree.fromstring(self._XMLDesc(PERSISTENT_XML))
                vcpus = tree.xpath("/domain/vcpus")
                for vcpu in vcpus:
                    parent = vcpu.getparent()
                    parent.remove(vcpu)
                    self._defineXML(etree.tostring(tree).decode())
        else:
            raise util.OperationError(
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

    def usage(self, previous=None):
        """
        CPU (percent of the host), disk read/write bytes and network rx/tx
        bits per second, for the stats view. With previous, the "sample" of an
        earlier answer, they are averages since then and nothing waits; without
        a usable one, over one second. A sample is usable for the same run of
        the VM (domain ID) on a host with the same CPUs and devices, at most
        USAGE_MAX_WINDOW seconds old. A value the host does not report (-1) or
        whose counter went back is None.
        """
        tree = ElementTree.fromstring(self._XMLDesc(0))
        disks = []
        for disk in tree.findall("devices/disk"):
            source, target = disk.find("source"), disk.find("target")
            if (
                disk.get("device") == "disk"
                and source is not None
                and any(source.get(name) for name in ("protocol", "file", "dev", "volume"))
                and target is not None
                and target.get("dev")
            ):
                disks.append(target.get("dev"))  # blockStats takes the target name
        # all NICs, in the order of the page's charts; one without a target is not measured
        nics = []
        for nic in tree.findall("devices/interface"):
            mac, target = nic.find("mac"), nic.find("target")
            nics.append([
                "" if mac is None else mac.get("address", ""),
                "" if target is None else target.get("dev", ""),
            ])

        if self.get_status() != 1:
            return {
                "cpu": 0,
                "disks": [{"dev": dev, "rd": 0, "wr": 0} for dev in disks],
                "nics": [{"dev": i, "rx": 0, "tx": 0} for i in range(len(nics))],
            }

        key = [self.instance.ID(), self.host_info[2], disks, nics]
        unread = (-1,) * 8

        def read():
            blocks = [self.instance.blockStats(dev) for dev in disks]
            links = [self.instance.interfaceStats(target) if target else unread for _, target in nics]
            return [
                self.instance.info()[4],
                [[stats[1], stats[3]] for stats in blocks],
                [[stats[0], stats[4]] for stats in links],
                time.monotonic(),
            ]

        def rates(before, after):
            seconds = after[3] - before[3]
            if before[0] > after[0] or not 0 < seconds <= USAGE_MAX_WINDOW:
                return None
            return {
                "cpu": 100 * (after[0] - before[0]) / (seconds * key[1] * 10**9),
                "disks": [
                    {"dev": dev, "rd": _rate(old[0], new[0], seconds), "wr": _rate(old[1], new[1], seconds)}
                    for dev, old, new in zip(disks, before[1], after[1])
                ],
                "nics": [
                    {"dev": i, "rx": _rate(old[0], new[0], seconds, 8), "tx": _rate(old[1], new[1], seconds, 8)}
                    for i, (old, new) in enumerate(zip(before[2], after[2]))
                ],
                "window": seconds,
            }

        counters = read()
        usage = None
        if previous is not None and previous.get("key") == key:
            usage = rates(previous["counters"], counters)
        if usage is None:
            before = counters
            time.sleep(1)
            counters = read()
            # None everywhere if the VM restarted meanwhile
            usage = rates(before, counters) or {
                "cpu": None,
                "disks": [{"dev": dev, "rd": None, "wr": None} for dev in disks],
                "nics": [{"dev": i, "rx": None, "tx": None} for i in range(len(nics))],
                "window": None,
            }
        usage["sample"] = {"key": key, "counters": counters}
        return usage

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

    def get_console_listener_addr(self, config=False):
        listener_addr = util.get_xml_path(
            self._XMLDesc(PERSISTENT_XML if config else 0), "/domain/devices/graphics/@listen"
        )
        if listener_addr is None:
            listener_addr = util.get_xml_path(
                self._XMLDesc(PERSISTENT_XML if config else 0), "/domain/devices/graphics/listen/@address"
            )
            if listener_addr is None:
                return "127.0.0.1"
        return listener_addr

    def console_listens_locally(self):
        """True if the persistent definition binds the console to loopback
        addresses or a Unix socket only. Anything the XML does not pin down
        counts as not local: listen type network, or no address at all (the
        host's default in qemu.conf)."""
        graphic = etree.fromstring(self._XMLDesc(PERSISTENT_XML)).find("devices/graphics")
        if graphic is None:
            return True  # no console
        addresses = [graphic.get("listen")]
        local_types = 0
        for listen in graphic.findall("listen"):
            if listen.get("type") == "address":
                addresses.append(listen.get("address"))
            elif listen.get("type") in ("socket", "none"):
                local_types += 1
            else:
                return False
        addresses = [a for a in addresses if a]
        if not addresses:
            return local_types > 0
        try:
            return all(ipaddress.ip_address(a).is_loopback for a in addresses)
        except ValueError:  # a host name
            return False

    def set_console_listener_addr(self, listener_addr):
        root = etree.fromstring(self._XMLDesc(PERSISTENT_XML))
        # The console is the first graphics device of the definition being
        # edited; the running VM may still have another type.
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

        newxml = etree.tostring(root).decode()
        return self._defineXML(newxml)

    def set_console_type(self, console_type):
        """VNC: a VNC graphics device on localhost; "pty": no graphics, so the
        serial console opens (libvirt adds the serial port for the console)."""
        root = etree.fromstring(self._XMLDesc(PERSISTENT_XML))
        devices = root.find("devices")
        for graphic in devices.findall("graphics"):
            devices.remove(graphic)
        if console_type == "vnc":
            etree.SubElement(devices, "graphics", type="vnc", port="-1", autoport="yes", listen="127.0.0.1")
        elif devices.find("console") is None:
            etree.SubElement(devices, "console", type="pty")
        return self._defineXML(etree.tostring(root).decode())

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

    def get_console_passwd(self, config=False):
        return util.get_xml_path(
            self._XMLDesc(PERSISTENT_XML if config else VIR_DOMAIN_XML_SECURE), "/domain/devices/graphics/@passwd"
        )

    def set_console_passwd(self, passwd):
        root = etree.fromstring(self._XMLDesc(PERSISTENT_XML))
        graphic = root.find("devices/graphics")
        if graphic is None:
            return False
        if passwd:
            graphic.set("passwd", passwd)
        else:
            with contextlib.suppress(Exception):
                graphic.attrib.pop("passwd")

        newxml = etree.tostring(root).decode()
        return self._defineXML(newxml)

    def set_console_keymap(self, keymap):
        root = etree.fromstring(self._XMLDesc(PERSISTENT_XML))
        graphic = root.find("devices/graphics")
        if graphic is None:
            return False
        if keymap != "auto":
            graphic.set("keymap", keymap)
        else:
            with contextlib.suppress(Exception):
                graphic.attrib.pop("keymap")

        newxml = etree.tostring(root).decode()
        self._defineXML(newxml)

    def get_console_keymap(self, config=False):
        return (
            util.get_xml_path(
                self._XMLDesc(PERSISTENT_XML if config else VIR_DOMAIN_XML_SECURE), "/domain/devices/graphics/@keymap"
            )
            or ""
        )

    def get_video_model(self, config=False):
        """:return only primary video card"""
        xml = self._XMLDesc(PERSISTENT_XML if config else VIR_DOMAIN_XML_SECURE)
        tree = etree.fromstring(xml)
        video_models = tree.xpath("/domain/devices/video/model")
        for model in video_models:
            if model.get("primary") == "yes" or len(video_models) == 1:
                return model.get("type")

    def set_video_model(self, model):
        """Changes only primary video card"""
        xml = self._XMLDesc(PERSISTENT_XML)
        tree = etree.fromstring(xml)
        video_models = tree.xpath("/domain/devices/video/model")
        for video_model in video_models:
            if video_model.get("primary") == "yes" or len(video_models) == 1:
                parent = video_model.getparent()
                parent.remove(video_model)
                etree.SubElement(parent, "model", type=model)
                self._defineXML(etree.tostring(tree).decode())
                return

    def resize_cpu(self, cur_vcpu, vcpu):
        """
        Function change ram and cpu on instance.
        """
        is_vcpus_enabled = self.get_vcpus()
        if is_vcpus_enabled:
            self.set_vcpu_hotplug(False)

        xml = self._XMLDesc(PERSISTENT_XML)
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
        # an active VM (running, paused, ...) changes only its current memory;
        # a paused guest's balloon driver applies it once it is resumed
        if self.instance.isActive():
            self.set_memory(cur_memory, VIR_DOMAIN_AFFECT_LIVE)
            self.set_memory(cur_memory, VIR_DOMAIN_AFFECT_CONFIG)
            return

        xml = self._XMLDesc(PERSISTENT_XML)
        tree = etree.fromstring(xml)

        mem_elem = tree.find("memory")
        mem_elem.text = str(memory)
        cur_mem_elem = tree.find("currentMemory")
        cur_mem_elem.text = str(cur_memory)

        new_xml = etree.tostring(tree).decode()
        self._defineXML(new_xml)

    def resize_disk(self, disks):
        """Grow disks. QEMU holds the lock of a running domain's image files and
        grows them itself; other volumes are grown by the storage pool first,
        then QEMU is told the new size. A pool that cannot resize volumes (LVM
        for one) raises VIR_ERR_NO_SUPPORT before anything changes."""
        active = self.instance.isActive()
        for disk in disks:
            vol = self.get_volume_by_path(disk["path"])
            if not active or vol.info()[0] != VIR_STORAGE_VOL_FILE:
                vol.resize(disk["size_new"])
            if active:
                self.instance.blockResize(disk["path"], disk["size_new"], VIR_DOMAIN_BLOCK_RESIZE_BYTES)

    def get_iso_media(self):
        iso = []
        for pool in self.wvm.listAllStoragePools(VIR_CONNECT_LIST_STORAGE_POOLS_ACTIVE):
            # refreshed so that an image copied to the pool by hand shows up
            with contextlib.suppress(libvirtError):
                pool.refresh(0)
            try:
                names = pool.listVolumes()
            except libvirtError:  # stopped or removed meanwhile
                continue
            iso.extend(name for name in names if name.lower().endswith(".iso"))
        return iso

    def paths_used_by_other_domains(self, own=()):
        """Paths another domain uses (see paths_in_use). The volumes in own
        are this VM's: their backing files do not count."""
        return self.paths_in_use(self.instance.UUIDString(), own)

    def split_disk_paths_by_use(self):
        """This VM's disk paths, split into (only this VM, also used by another
        domain). With external snapshots, the files below a disk that the
        snapshots were taken on, and their memory files, are the VM's too."""
        self.refresh_instance_pools()
        own = [disk["path"] for disk in self.get_disk_devices() if disk["path"]]
        own += self._snapshot_chain_files(own)
        used_elsewhere = self.paths_used_by_other_domains(own)
        # a kept file keeps the files below it
        for path in [path for path in own if path in used_elsewhere]:
            while (path := self._backing_path(path)) and path not in used_elsewhere:
                used_elsewhere.add(path)
        return (
            [path for path in own if path not in used_elsewhere],
            [path for path in own if path in used_elsewhere],
        )

    def _snapshot_chain_files(self, tops):
        """The files of this VM's external snapshots that these disk images
        grow from or that grow from them: the backing files snapshots were
        taken on, down the chain, the overlays of snapshots off the chain
        (newer ones kept after a revert), and the snapshots' memory files. A
        backing file the VM started from (a template) is no snapshot point
        and ends the chain; an overlay that does not grow from the chain (a
        disk detached since) stays."""
        points, overlays, memory = set(), set(), []
        for snap in self.instance.listAllSnapshots(VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL):
            tree = etree.fromstring(snap.getXMLDesc(0))
            memory += tree.xpath("memory/@file")
            overlays.update(tree.xpath("disks/disk/source/@file"))
            saved = self._saved_definition(tree)
            if saved is not None:
                points.update(self._disk_sources(saved).values())
        files = list(tops)
        for path in tops:
            while (path := self._backing_path(path)) in points and path not in files:
                files.append(path)
        grew = True
        while grew:
            grew = False
            for top in overlays.difference(files):
                if top in files:  # reached by a branch in this pass
                    continue
                branch, path = [top], top
                while (path := self._backing_path(path)) in points | overlays and path not in files:
                    branch.append(path)
                if path in files:
                    files += branch
                    grew = True
        return files[len(tops):] + memory

    def _backing_path(self, path):
        """The backing file of a volume; None if it has none or is in no pool.
        Any other error is raised: a chain cut short would let a file a kept
        one needs count as deletable."""
        try:
            vol = self.get_volume_by_path(path)
        except libvirtError as err:
            if err.get_error_code() != VIR_ERR_NO_STORAGE_VOL:
                raise
            return None
        return util.get_xml_path(vol.XMLDesc(0), "/volume/backingStore/path")

    def _snapshotCreateXML(self, xml, flag):
        self.instance.snapshotCreateXML(xml, flag)

    def create_snapshot(self, name, desc=None):
        if self.instance.snapshotListNames(VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL):
            raise util.OperationError("The VM has external snapshots; internal snapshots cannot be mixed with them")
        state = "shutoff" if self.get_status() == 5 else "running"
        name_esc = util.xml_escape(name)
        desc_esc = util.xml_escape(desc) if desc else ""
        xml = """<domainsnapshot>
                     <name>%s</name>
                     <description>%s</description>
                     <state>%s</state>
                     <creationTime>%d</creationTime>""" % (
            name_esc,
            desc_esc,
            state,
            time.time(),
        )
        # libvirt decides whether this firmware/NVRAM supports internal
        # snapshots; the domain definition is never rewritten for it.
        xml += self._XMLDesc(VIR_DOMAIN_XML_SECURE)
        xml += """<active>0</active>
                  </domainsnapshot>"""
        self._snapshotCreateXML(xml, 0)

    def create_external_snapshot(self, name, desc="", memory=False, quiesce=False, free_percent=10, free_min_gib=1):
        """A disk-only snapshot, or with memory too (running VMs only). Every
        disk gets a libvirt-named overlay next to it; the memory file goes
        next to the first disk. quiesce: the guest agent freezes the guest's
        file systems for a disk-only snapshot of a running VM (libvirt
        accepts it only without memory, which keeps the whole state anyway).
        free_percent, free_min_gib: the free space each pool keeps (see
        _check_snapshot_space)."""
        if not SNAPSHOT_NAME.fullmatch(name):
            raise util.OperationError(
                "Snapshot names are 1-64 letters, digits, '.', '_' or '-' and do not start with '.'"
            )
        if quiesce:
            if memory:
                raise util.OperationError("A snapshot with memory is not quiesced; it keeps the whole guest state")
            if self.get_status() != 1:
                raise util.OperationError("Only a running VM's file systems can be frozen")
            if not self.is_agent_ready():
                raise util.OperationError("The QEMU guest agent is not connected; it freezes the file systems")
        self._check_snapshot_state()
        if self.instance.snapshotListNames(VIR_DOMAIN_SNAPSHOT_LIST_INTERNAL):
            raise util.OperationError("The VM has internal snapshots; external snapshots cannot be mixed with them")
        if name in self.instance.snapshotListNames(0):
            raise util.OperationError(f"A snapshot named {name} already exists")
        if self.instance.hasCurrentSnapshot(0):
            if self.instance.snapshotCurrent(0).numChildren(0):
                raise util.OperationError("Newer snapshots exist after the last revert; delete them first")
        elif self.instance.snapshotListNames(0):
            # only after changes outside WebVirtCloud; a create would start a second root
            raise util.OperationError("No snapshot is current; revert to a snapshot first")
        tree = etree.fromstring(self._XMLDesc(0))
        for disk in tree.xpath("devices/disk"):
            dev = disk.xpath("string(target/@dev)")
            if disk.get("device") in ("cdrom", "floppy"):
                if disk.xpath("source/@file|source/@dev|source/@name"):
                    raise util.OperationError(f"Eject the media from {dev} first")
            elif disk.get("type") != "file":
                raise util.OperationError(f"Disk {dev} is not a file; external snapshots need file disks")
        disks = list(self._disk_sources(tree).values())
        # free space, and the top overlays, are known to the pools only after
        # a refresh; nothing has changed yet when it fails
        try:
            self.refresh_instance_pools()
        except libvirtError as err:
            raise util.OperationError(
                f"The storage pools could not be refreshed, so their free space is unknown: {err}"
            ) from None
        memory_xml, memory_pool = self._snapshot_memory(name, disks) if memory else ("", None)
        self._check_snapshot_space(disks, memory_pool, free_percent, free_min_gib)
        xml = (
            f"<domainsnapshot><name>{name}</name>"
            f"<description>{util.xml_escape(desc)}</description>{memory_xml}</domainsnapshot>"
        )
        flags = VIR_DOMAIN_SNAPSHOT_CREATE_ATOMIC
        if not memory:
            flags |= VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY
        if quiesce:
            self.ping_agent()
            flags |= VIR_DOMAIN_SNAPSHOT_CREATE_QUIESCE
        self._snapshotCreateXML(xml, flags)
        self._refresh_pools_after_snapshot()

    def _snapshot_memory(self, name, disks):
        """The <memory> element of a snapshot that saves memory, and the
        storage pool its file goes into: the pool of the first disk."""
        if self.get_status() != 1:
            raise util.OperationError("Memory is saved only from a running VM")
        if not disks:
            raise util.OperationError("The VM has no disk to keep its memory next to")
        try:
            pool = self.get_volume_by_path(disks[0]).storagePoolLookupByVolume()
        except libvirtError:
            raise util.OperationError(f"{disks[0]} is not in a storage pool; memory is saved only into one") from None
        path = os.path.join(os.path.dirname(disks[0]), f"{self.get_uuid()}.{name}.mem")
        return f"<memory snapshot='external' file='{util.xml_escape(path)}'/>", pool.name()

    def _check_snapshot_space(self, disks, memory_pool, free_percent, free_min_gib):
        """Each storage pool with a disk of the VM keeps free_percent of the
        virtual size of those disks free, at least free_min_gib GiB, and the
        pool of the memory file the VM's memory on top. The
        overlays grow as the guest writes, and a delete merges them down.
        This is checked before the snapshot only; nothing is reserved. A
        disk in no pool is not checked."""
        needed, pools = {}, {}
        for path in disks:
            try:
                vol = self.get_volume_by_path(path)
            except libvirtError as err:
                if err.get_error_code() != VIR_ERR_NO_STORAGE_VOL:
                    raise
                continue
            pool = vol.storagePoolLookupByVolume()
            pools[pool.name()] = pool
            needed[pool.name()] = needed.get(pool.name(), 0) + vol.info()[1] * free_percent / 100
        for name in needed:
            needed[name] = max(needed[name], free_min_gib * 1024**3)
        if memory_pool:
            needed[memory_pool] += self.get_cur_memory() * 1024 * 1024
        for name, size in needed.items():
            free = pools[name].info()[3]
            if free < size:
                raise util.OperationError(
                    f"Storage pool {name} has {free / 1024**3:.1f} GiB free; the snapshot needs {size / 1024**3:.1f} GiB "
                    f"({free_percent:g}% of the VM's disks in it, at least {free_min_gib:g} GiB, "
                    "and the memory if it is saved)"
                )

    def check_external_revert(self, name):
        """Refuses a revert that cannot work, before anything changes; returns
        the snapshot."""
        snap = self._snapshot(name, external=True)
        self._check_snapshot_state()
        tree = etree.fromstring(snap.getXMLDesc(0))
        # Snapshots of UEFI VMs taken before WebVirtCloud used libvirt's
        # snapshot API saved the loader switched to rom; a revert would
        # restore that.
        saved = self._saved_definition(tree)
        saved_loader = saved.xpath("string(os/loader/@type)") if saved is not None else ""
        current_loader = util.get_xml_path(self._XMLDesc(PERSISTENT_XML), "/domain/os/loader/@type")
        if saved_loader == "rom" and current_loader == "pflash":
            raise util.OperationError(
                "This snapshot was taken by an older version on a UEFI VM and cannot be reverted; delete it instead"
            )
        return snap

    def revert_external_snapshot(self, name):
        """libvirt returns the disks and the definition to the snapshot's. A
        disk-only snapshot keeps the VM running, paused or shut off as it is;
        a snapshot with memory resumes the VM as it was saved. Returns the
        files libvirt left behind (see _left_behind)."""
        snap = self.check_external_revert(name)
        tree = etree.fromstring(snap.getXMLDesc(0))
        if tree.find("memory[@snapshot='external']") is not None:
            flags = 0
        else:
            flags = {1: VIR_DOMAIN_SNAPSHOT_REVERT_RUNNING, 3: VIR_DOMAIN_SNAPSHOT_REVERT_PAUSED}.get(
                self.get_status(), 0
            )
        before = self._snapshot_files()
        # libvirt names the new overlays after the second, so a revert within
        # the second of the previous one finds them taken, after it has
        # already stopped a running VM; one retry a second later finishes it.
        try:
            self.instance.revertToSnapshot(snap, flags)
        except libvirtError as err:
            if err.get_error_code() != VIR_ERR_CONFIG_UNSUPPORTED or "already exists" not in str(err):
                raise
            time.sleep(1)
            try:
                self.instance.revertToSnapshot(snap, flags)
            except libvirtError as retry_err:
                state = "running" if self.instance.isActive() else "shut off"
                raise util.OperationError(
                    f"The revert failed twice; try again in a moment ({retry_err}). The VM is {state}."
                ) from None
        return self._left_behind(before)

    def delete_external_snapshot(self, name):
        """libvirt merges the snapshot's overlays and removes its files.
        Returns the files it left behind (see _left_behind)."""
        snap = self._snapshot(name, external=True)
        self._check_snapshot_state()
        before = self._snapshot_files()
        snap.delete(0)
        return self._left_behind(before)

    def _snapshot_files(self):
        """(disks, snapshot files, snapshot points): the files each disk uses
        by target, the external snapshots' own files (overlays, memory), and
        the files snapshots were taken on, which libvirt's overlays sit on."""
        disks = {
            disk.xpath("string(target/@dev)"): set(disk.xpath(".//source/@file"))
            for disk in etree.fromstring(self.instance.XMLDesc(0)).xpath("devices/disk[@device='disk']")
        }
        own, points = set(), set()
        for snap in self.instance.listAllSnapshots(VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL):
            tree = etree.fromstring(snap.getXMLDesc(0))
            own.update(tree.xpath("disks/disk/source/@file|memory/@file"))
            saved = self._saved_definition(tree)
            if saved is not None:
                points.update(self._disk_sources(saved).values())
        return disks, own, points | own

    def snapshot_files_state(self):
        """_snapshot_files as plain lists, recorded before a snapshot change."""
        disks, own, points = self._snapshot_files()
        return {"disks": {dev: sorted(files) for dev, files in disks.items()},
                "own": sorted(own), "points": sorted(points)}

    def left_behind_since(self, state):
        """_left_behind from a state recorded by snapshot_files_state."""
        before = ({dev: set(files) for dev, files in state["disks"].items()}, set(state["own"]), set(state["points"]))
        return self._left_behind(before)

    def _refresh_pools_after_snapshot(self):
        """Refresh the pools once libvirt has changed the snapshot files. The
        snapshot operation is done by then, so an error is only logged;
        returns whether the pools are current."""
        try:
            self.refresh_instance_pools()
        except libvirtError as err:
            logger.warning("Storage pools of %s were not refreshed after a snapshot change: %s", self.instance.name(), err)
            return False
        return True

    def _left_behind(self, before):
        """Files libvirt merged or discarded but could not remove: it only
        logs a warning then (on NFS it removes them as the qemu user, who
        needs write access to their directory). Only a snapshot's own file or
        an overlay on a snapshot point counts; a disk a revert detached is
        kept on purpose, and a file another VM on this host uses (or one
        below it) is not reported. A file outside every storage pool is not
        checked, nor is anything when the pools could not be refreshed: a
        stale pool still lists the removed files."""
        disks, own, points = before
        if not self._refresh_pools_after_snapshot():
            return []
        now_disks, now_own, _ = self._snapshot_files()
        # only disks still attached: one a revert detached keeps its files,
        # whatever they sit on
        attached = set().union(*(files for dev, files in disks.items() if dev in now_disks))
        left = []
        for path in sorted((attached | own) - set().union(now_own, *now_disks.values())):
            try:
                vol = self.get_volume_by_path(path)
                if path not in own and util.get_xml_path(vol.XMLDesc(0), "/volume/backingStore/path") not in points:
                    continue
            except libvirtError:  # not in a pool, or removed meanwhile
                continue
            left.append(path)
        if left:
            # another VM on this host may use one; their own backing files
            # do not keep each other, but a file in use keeps the files below it
            in_use = self.paths_in_use(own=left)
            for path in [path for path in left if path in in_use]:
                while (path := self._backing_path(path)) and path not in in_use:
                    in_use.add(path)
            left = [path for path in left if path not in in_use]
        return left

    @staticmethod
    def _disk_sources(xml):
        """Target dev -> source file of the disks (not CD-ROMs) in a domain definition."""
        tree = etree.fromstring(xml) if isinstance(xml, str) else xml
        return {
            disk.xpath("string(target/@dev)"): disk.xpath("string(source/@file|source/@dev|source/@name)")
            for disk in tree.xpath("devices/disk[@device='disk']")
        }

    @staticmethod
    def _saved_definition(tree):
        """The definition a revert to this snapshot restores as the persistent one."""
        definition = tree.find("inactiveDomain")
        return tree.find("domain") if definition is None else definition

    def get_snapshot(self, flag):
        """Snapshots of one kind (VIR_DOMAIN_SNAPSHOT_LIST_INTERNAL or
        _EXTERNAL), with whether each saved memory, is the current one, and
        which disks a revert to it detaches: from the persistent definition,
        and on a running VM from the live one too (a disk hot-plugged only)."""
        persistent_disks = self._disk_sources(self._XMLDesc(PERSISTENT_XML))
        live_disks = self._disk_sources(self._XMLDesc(0)) if self.instance.isActive() else {}
        snapshots = []
        for snap in self.instance.listAllSnapshots(flag):
            tree = etree.fromstring(snap.getXMLDesc(0))
            definition = self._saved_definition(tree)
            saved_disks = self._disk_sources(definition) if definition is not None else {}
            # a revert of a running VM restores what ran when the snapshot was taken
            ran = tree.find("domain")
            saved_live_disks = self._disk_sources(ran) if ran is not None else saved_disks
            detaches = {dev: path for dev, path in persistent_disks.items() if dev not in saved_disks}
            for dev, path in live_disks.items():
                if dev not in saved_live_disks:
                    detaches.setdefault(dev, path)
            snapshots.append(
                {
                    "date": datetime.fromtimestamp(int(tree.findtext("creationTime"))),
                    "name": snap.getName(),
                    "description": tree.findtext("description") or "",
                    "memory": tree.find("memory[@snapshot='external']") is not None,
                    "current": bool(snap.isCurrent(0)),
                    "detaches": [{"dev": dev, "path": path} for dev, path in detaches.items()],
                }
            )
        return snapshots

    def get_snapshot_jobs(self):
        """Block jobs (snapshot merges) running on the VM's disks. libvirt
        merges a shut-off VM's snapshot as an offline block job; a libvirt
        without offline jobs refuses the query for an inactive VM, which
        means no job."""
        active = self.instance.isActive()
        jobs = []
        for dev in self._disk_sources(self._XMLDesc(0 if active else PERSISTENT_XML)):
            try:
                info = self.instance.blockJobInfo(dev, 0)
            except libvirtError as err:
                if active or err.get_error_code() != VIR_ERR_OPERATION_INVALID:
                    raise
                info = None
            if info:
                jobs.append({"dev": dev, "cur": info["cur"], "end": info["end"]})
        return jobs

    def _snapshot(self, name, external):
        """The named snapshot; a snapshot of the other kind is refused."""
        flag = VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL if external else VIR_DOMAIN_SNAPSHOT_LIST_INTERNAL
        if name not in self.instance.snapshotListNames(flag):
            kind = "external" if external else "internal"
            raise util.OperationError(f"The VM has no {kind} snapshot named {name}")
        return self.instance.snapshotLookupByName(name, 0)

    def _check_snapshot_state(self):
        """Refusals shared by external snapshot create, revert and delete. The
        internal/external mix is checked only on create, so a VM that is
        already mixed can still be cleaned up."""
        if self.instance.hasManagedSaveImage(0):
            raise util.OperationError("The VM has a saved state; start it or remove the saved state first")
        if self.get_snapshot_jobs():
            raise util.OperationError("A snapshot job is still running on this VM; try again when it ends")

    def snapshot_delete(self, snapshot):
        self._snapshot(snapshot, external=False).delete(0)

    def snapshot_revert(self, snapshot):
        self.instance.revertToSnapshot(self._snapshot(snapshot, external=False), 0)

    def get_managed_save_image(self):
        return self.instance.hasManagedSaveImage(0)

    def get_wvmStorage(self, pool):
        return wvmStorage(self.host, self.login, self.passwd, self.conn, pool)

    def get_wvmStorages(self):
        return wvmStorages(self.host, self.login, self.passwd, self.conn)

    def refresh_instance_pools(self):
        """Refresh the pools whose target directory holds one of the VM's
        disks; a disk outside every pool has none to refresh."""
        target_paths = {os.path.dirname(disk["path"]) for disk in self.get_disk_devices() if disk.get("path")}
        storages = self.get_wvmStorages()
        for target_path in target_paths:
            pool = storages.get_pool_by_target(target_path)
            if pool is not None:
                pool.refresh(0)

    def fix_mac(self, mac):
        if ":" in mac:
            return mac
        # if mac does not contain ":", try to split into tuples and join with ":"
        n = 2
        mac_tuples = [mac[i : i + n] for i in range(0, len(mac), n)]
        return ":".join(mac_tuples)

    def _clone_definition(self, clone_data, uuid):
        """The VM's persistent definition renamed to the clone, with its UUID,
        title, description and MACs; returns it and the (source, dev) of each
        disk to copy. Disks without a source are dropped. Raises before
        anything is allocated."""
        if clone_data["name"] in self.get_instances():
            raise ValueError("An instance with the clone name already exists")

        tree = etree.fromstring(self._XMLDesc(PERSISTENT_XML))
        tree.find("name").text = clone_data["name"]
        uuid_el = tree.find("uuid")
        if uuid_el is None:
            uuid_el = etree.SubElement(tree, "uuid")
        uuid_el.text = uuid
        self._set_options(
            tree,
            {
                "title": clone_data.get("clone-title", ""),
                "description": clone_data.get("clone-description", ""),
            },
        )

        disks = []
        for disk in list(tree.findall("devices/disk")):
            if disk.get("device") != "disk":
                continue
            source = disk.find("source")
            if source is None or not any(source.get(key) for key in ("file", "dev", "name", "volume")):
                disk.getparent().remove(disk)
                continue
            supported = source.get("file") or source.get("dev") or (
                source.get("protocol") == "rbd" and source.get("name")
            )
            target = disk.find("target")
            dev = target.get("dev") if target is not None else None
            if not supported or not dev or not clone_data.get("disk-" + dev):
                raise ValueError("Cannot clone a disk without a supported source and destination")
            disks.append((source, dev))

        for num, net in enumerate(tree.findall("devices/interface")):
            mac = clone_data.get(f"clone-net-mac-{num}")
            if not mac:
                raise ValueError(f"No MAC address for network interface {num}")
            net.find("mac").set("address", self.fix_mac(mac))

        nvram = tree.find("os/nvram")
        if nvram is not None and nvram.get("type", "file") != "file":
            raise util.OperationError("Cannot clone a VM whose NVRAM is not a file")
        return tree, disks

    def _clone_volume_xml(self, name, capacity, vol_format, owner_uid, owner_gid):
        return f"""<volume>
                      <name>{util.xml_escape(name)}</name>
                      <capacity>{capacity}</capacity>
                      <allocation>0</allocation>
                      <target>
                        <format type='{vol_format}'/>
                        <permissions>
                          <owner>{owner_uid}</owner>
                          <group>{owner_gid}</group>
                          <mode>0644</mode>
                          <label>virt_image_t</label>
                        </permissions>
                        <compat>1.1</compat>
                        <features><lazy_refcounts/></features>
                      </target>
                    </volume>"""

    def define_clone(self, clone_data, uuid, paths):
        """Defines the clone with each copied disk's source set from paths
        ({dev: new path}) and its own copy of the VM's UEFI variables (NVRAM).
        The NVRAM copy is removed if the definition fails. Returns the
        clone's UUID."""
        tree, disks = self._clone_definition(clone_data, uuid)
        for source, dev in disks:
            source.set("file" if source.get("file") else "dev" if source.get("dev") else "name", paths[dev])

        # the UEFI variables: a path as text, or a <source file=...> since libvirt 8.5
        nvram = tree.find("os/nvram")
        nvram_source = nvram.find("source") if nvram is not None else None
        nvram_path = None
        if nvram is not None:
            nvram_path = nvram_source.get("file") if nvram_source is not None else (nvram.text or "").strip()

        if not nvram_path:
            return self._defineXML(etree.tostring(tree).decode()).UUIDString()
        # the clone starts with the VM's UEFI variables: boot entries, enrolled keys
        if os.path.dirname(nvram_path) == NVRAM_DIR:
            pools = self._nvram_pool()
        else:  # a volume of a pool; libvirtError when no pool holds it
            pools = contextlib.nullcontext(self.get_volume_by_path(nvram_path).storagePoolLookupByVolume())
        with pools as pool:
            original = pool.storageVolLookupByName(os.path.basename(nvram_path))
            # same format, owner and mode as the original: the domain names the format,
            # and qemu may run without libvirt changing the file's owner
            target = etree.fromstring(original.XMLDesc(0)).find("target")
            volume = etree.Element("volume")
            etree.SubElement(volume, "name").text = clone_data["name"] + "_VARS" + os.path.splitext(nvram_path)[1]
            etree.SubElement(volume, "capacity").text = "0"
            copy_target = etree.SubElement(volume, "target")
            for tag in ("format", "permissions"):
                if target.find(tag) is not None:
                    copy_target.append(target.find(tag))
            copy = pool.createXMLFrom(etree.tostring(volume).decode(), original, 0)
            if nvram_source is not None:
                nvram_source.set("file", copy.path())
            else:
                nvram.text = copy.path()
            try:
                return self._defineXML(etree.tostring(tree).decode()).UUIDString()
            except Exception as err:
                try:
                    copy.delete(0)
                except libvirtError:
                    raise util.OperationError(
                        f"Clone failed ({err}); remove these copies by hand: {copy.path()}"
                    ) from err
                raise

    def clone_instance(self, clone_data, uuid):
        """Copy a shut-off VM, with its disks and UEFI variables (NVRAM).
        Inputs are checked before anything is allocated, and on failure only
        the volumes this call created are removed. Returns the clone's UUID."""
        if self.get_status() != 5:
            # A running guest keeps writing while its disks are copied.
            raise util.OperationError("Shut the VM down before cloning it")
        _, disks = self._clone_definition(clone_data, uuid)

        paths = {}  # dev: path of its copy
        created = []  # paths of volumes this call created
        try:
            for source, dev in disks:
                target_file = clone_data["disk-" + dev]
                meta_prealloc = bool(clone_data.get("meta-" + dev))
                if source.get("file"):
                    vol = self.get_volume_by_path(source.get("file"))
                    vol_format = util.get_xml_path(vol.XMLDesc(0), "/volume/target/format/@type")
                    new_vol = vol.storagePoolLookupByVolume().createXMLFrom(
                        self._clone_volume_xml(
                            target_file, 0, vol_format, clone_data["disk_owner_uid"], clone_data["disk_owner_gid"]
                        ),
                        vol,
                        meta_prealloc and vol_format == "qcow2",
                    )
                    created.append(new_vol.path())
                    paths[dev] = new_vol.path()
                elif source.get("protocol") == "rbd":
                    vol = self.get_volume_by_path(source.get("name"))
                    vol_format = util.get_xml_path(vol.XMLDesc(0), "/volume/target/format/@type")
                    new_vol = vol.storagePoolLookupByVolume().createXMLFrom(
                        f"""<volume type='network'>
                              <name>{target_file}</name>
                              <capacity>0</capacity>
                              <allocation>0</allocation>
                              <target><format type='{vol_format}'/></target>
                            </volume>""",
                        vol,
                        meta_prealloc,
                    )
                    created.append(new_vol.path())
                    paths[dev] = f"{os.path.dirname(source.get('name'))}/{target_file}"
                else:
                    vol = self.get_volume_by_path(source.get("dev"))
                    pool_name = util.get_xml_path(vol.storagePoolLookupByVolume().XMLDesc(0), "/pool/name")
                    storage = self.get_wvmStorage(pool_name)
                    name = storage.clone_volume(vol.name(), target_file)
                    new_path = storage.get_volume(name).path()
                    created.append(new_path)
                    paths[dev] = new_path

            return self.define_clone(clone_data, uuid, paths)
        except Exception as err:
            leftovers = []
            for path in reversed(created):
                try:
                    self.get_volume_by_path(path).delete(0)
                except libvirtError:
                    leftovers.append(path)
            if leftovers:
                raise util.OperationError(f"Clone failed ({err}); remove these copies by hand: {', '.join(leftovers)}") from err
            raise

    def live_clone_targets(self, clone_data, free_percent=10, free_min_gib=1):
        """Refuses a live clone that cannot work, before anything is
        allocated; returns the new volume of each copied disk, in disk order:
        in the source volume's pool, at its virtual capacity and format. Each
        pool keeps the copies plus free_percent of them, at least
        free_min_gib GiB, free (the snapshots' rule); checked only, nothing
        is reserved."""
        if self.wvm.getLibVersion() < LIVE_CLONE_MIN_LIBVIRT:
            raise util.OperationError("Live clone needs libvirt 11.10 or later; shut the VM down to clone it")
        tree, disks = self._clone_definition(clone_data, "")
        if tree.find("devices/tpm") is not None:
            raise util.OperationError("A VM with a TPM is cloned only shut down")
        for source, dev in disks:
            if not source.get("file"):
                raise util.OperationError(f"Disk {dev} is not a local file; shut the VM down to clone it")
            if source.getparent().find("shareable") is not None:
                raise util.OperationError(f"Disk {dev} is shareable; shut the VM down to clone it")
        if self.instance.jobInfo()[0] != VIR_DOMAIN_JOB_NONE:
            raise util.OperationError("Another job is running on the VM; clone it when that ends")

        targets, pools, copied = [], {}, {}
        for source, dev in disks:
            vol = self.get_volume_by_path(source.get("file"))
            pool = vol.storagePoolLookupByVolume()
            name = clone_data["disk-" + dev]
            try:
                pool.storageVolLookupByName(name)
            except libvirtError as err:
                if err.get_error_code() != VIR_ERR_NO_STORAGE_VOL:
                    raise
            else:
                raise util.OperationError(f"Volume {name} already exists in storage pool {pool.name()}")
            capacity = vol.info()[1]
            pools[pool.name()] = pool
            copied[pool.name()] = copied.get(pool.name(), 0) + capacity
            targets.append(
                {
                    "dev": dev,
                    "pool": pool.name(),
                    "name": name,
                    "path": os.path.join(util.get_xml_path(pool.XMLDesc(0), "/pool/target/path"), name),
                    "capacity": capacity,
                    "format": util.get_xml_path(vol.XMLDesc(0), "/volume/target/format/@type"),
                }
            )
        for name, size in copied.items():
            needed = size + max(size * free_percent / 100, free_min_gib * 1024**3)
            free = pools[name].info()[3]
            if free < needed:
                raise util.OperationError(
                    f"Storage pool {name} has {free / 1024**3:.1f} GiB free; the clone needs {needed / 1024**3:.1f} GiB "
                    f"(the copied disks, plus {free_percent:g}% of them, at least {free_min_gib:g} GiB)"
                )
        return targets

    def create_clone_target(self, target, owner_uid, owner_gid):
        """An empty volume for a copied disk; libvirt refuses one that exists.
        Returns its path."""
        pool = self.wvm.storagePoolLookupByName(target["pool"])
        xml = self._clone_volume_xml(target["name"], target["capacity"], target["format"], owner_uid, owner_gid)
        return pool.createXML(xml, 0).path()

    def begin_clone_backup(self, targets):
        """Starts libvirt's push backup of the targets' disks into their
        volumes. The VM keeps running when the guest shuts down meanwhile."""
        disks = "".join(
            f"<disk name='{util.xml_escape(t['dev'])}' backup='yes' type='file'>"
            f"<target file='{util.xml_escape(t['path'])}'/><driver type='{util.xml_escape(t['format'])}'/></disk>"
            for t in targets
        )
        self.instance.backupBegin(
            f"<domainbackup mode='push'><disks>{disks}</disks></domainbackup>",
            None,
            VIR_DOMAIN_BACKUP_BEGIN_REUSE_EXTERNAL | VIR_DOMAIN_BACKUP_BEGIN_PRESERVE_SHUTDOWN_DOMAIN,
        )

    def backup_targets(self):
        """The target paths of the running backup; None when none runs."""
        try:
            xml = self.instance.backupGetXMLDesc(0)
        except libvirtError as err:
            if err.get_error_code() == VIR_ERR_NO_DOMAIN_BACKUP:
                return None
            raise
        return set(etree.fromstring(xml).xpath("disks/disk/target/@file"))

    def backup_progress(self):
        """(bytes copied, bytes to copy) of the running backup; None when
        none runs."""
        stats = self.instance.jobStats(0)
        if (
            stats.get("type", VIR_DOMAIN_JOB_NONE) == VIR_DOMAIN_JOB_NONE
            or stats.get("operation") != VIR_DOMAIN_JOB_OPERATION_BACKUP
        ):
            return None
        return stats.get("disk_processed", 0), stats.get("disk_total", 0)

    def backup_result(self):
        """(success, libvirt's error) of the completed backup, kept for later
        reads; None when libvirt has no completed backup."""
        stats = self.instance.jobStats(VIR_DOMAIN_JOB_STATS_COMPLETED | VIR_DOMAIN_JOB_STATS_KEEP_COMPLETED)
        if stats.get("operation") != VIR_DOMAIN_JOB_OPERATION_BACKUP or "success" not in stats:
            return None
        return bool(stats["success"]), stats.get("errmsg") or ""

    def discard_backup_result(self):
        """Drops the result libvirt keeps of the VM's last completed job, so
        a later backup_result() can only be of a backup started after this."""
        self.instance.jobStats(VIR_DOMAIN_JOB_STATS_COMPLETED)

    def abort_backup(self):
        self.instance.abortJob()

    def ping_agent(self):
        """A frozen or dead agent fails here in AGENT_TIMEOUT seconds. The
        freeze that follows is libvirt's, without a timeout: a timed freeze
        could still end in the guest after its thaw failed, leaving the guest
        frozen."""
        agent_command(self.instance, "guest-ping")

    def fs_freeze(self):
        self.ping_agent()
        self.instance.fsFreeze(None, 0)

    def fs_thaw(self):
        self.instance.fsThaw(None, 0)

    def add_network(
        self, mac_address, source, source_type="net", model="virtio", nwfilter=None
    ):

        if source_type == "net":
            interface_type = "network"
        elif source_type == "bridge":
            interface_type = "bridge"
        else:
            interface_type = "direct"

        # Built with lxml so posted values are escaped, never parsed as XML.
        iface = etree.Element("interface", type=interface_type)
        if mac_address:  # otherwise libvirt generates one
            etree.SubElement(iface, "mac", address=mac_address)
        if interface_type == "network":
            etree.SubElement(iface, "source", network=source)
        elif interface_type == "direct":
            etree.SubElement(iface, "source", dev=source, mode="bridge")
        else:
            etree.SubElement(iface, "source", bridge=source)
        if model and model != "default":  # default: no model, libvirt chooses
            etree.SubElement(iface, "model", type=model)
        if nwfilter:
            etree.SubElement(iface, "filterref", filter=nwfilter)
        self._attach_device(etree.tostring(iface).decode())

    def _attach_device(self, xml):
        """Attach to the persistent definition and, when the VM is active, to
        the running one, in one call. QEMU checks a copy of the persistent
        definition before the hotplug, so a conflict there (a disk target or
        an agent channel already pending) changes neither, and a NIC without
        a MAC gets the same one in both. Still possible: a failure after a
        successful hotplug leaves the device in the running VM only, and a
        SCSI controller added for a disk that then fails to plug stays. An
        error never proves that a new volume is unused."""
        flags = VIR_DOMAIN_AFFECT_CONFIG
        if self.instance.isActive():
            flags |= VIR_DOMAIN_AFFECT_LIVE
        self.instance.attachDeviceFlags(xml, flags)

    def _definitions(self):
        """(XMLDesc flags, affect flag) of the definitions a device edit applies to:
        the running one when the VM is active (running or paused), and the
        persistent one. Each is edited from its own XML."""
        definitions = [(PERSISTENT_XML, VIR_DOMAIN_AFFECT_CONFIG)]
        if self.instance.isActive():
            definitions.insert(0, (VIR_DOMAIN_XML_SECURE, VIR_DOMAIN_AFFECT_LIVE))
        return definitions

    def _nic(self, xml_flags, mac_address):
        found = etree.fromstring(self._XMLDesc(xml_flags)).xpath(
            "./devices/interface[mac/@address=$mac]", mac=mac_address
        )
        return found[0] if found else None

    def delete_network(self, mac_address):
        """Detach the NIC; returns its persistent XML, or None if there is none."""
        removed = None
        for xml_flags, affect in self._definitions():
            nic = self._nic(xml_flags, mac_address)
            if nic is not None:
                removed = etree.tostring(nic).decode()
                self.instance.detachDeviceFlags(removed, affect)
        return removed

    def change_network(self, old_mac, mac, source, source_type, model, nwfilter):
        """Edit the NIC with old_mac in the persistent definition, in place.

        Settings this form does not edit (QoS, link state, driver, PCI address)
        stay. A running VM gets the change at its next start.
        """
        tree = etree.fromstring(self._XMLDesc(PERSISTENT_XML))
        found = tree.xpath("./devices/interface[mac/@address=$mac]", mac=old_mac)
        if not found:
            raise util.OperationError(f"No network interface with MAC {old_mac}")
        iface = found[0]

        iface_type = {"net": "network", "bridge": "bridge"}.get(source_type, "direct")
        iface.set("type", iface_type)
        for old_source in iface.findall("source"):
            iface.remove(old_source)
        source_attrs = {"network": {"network": source}, "bridge": {"bridge": source}}.get(
            iface_type, {"dev": source, "mode": "bridge"}
        )
        iface.insert(1, etree.Element("source", **source_attrs))

        iface.find("mac").set("address", mac)
        for old_model in iface.findall("model"):
            iface.remove(old_model)
        if model and model != "default":  # default: no model, libvirt chooses
            etree.SubElement(iface, "model", type=model)
        for old_filter in iface.findall("filterref"):
            iface.remove(old_filter)
        if nwfilter:
            etree.SubElement(iface, "filterref", filter=nwfilter)

        self._defineXML(etree.tostring(tree).decode())

    def set_link_state(self, mac_address, state):
        for xml_flags, affect in self._definitions():
            nic = self._nic(xml_flags, mac_address)
            if nic is None:
                continue
            for link in nic.findall("link"):
                nic.remove(link)
            etree.SubElement(nic, "link", state=state)
            self.instance.updateDeviceFlags(etree.tostring(nic).decode(), affect)

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
        xml = self._XMLDesc(PERSISTENT_XML)
        tree = etree.fromstring(xml)

        self._set_options(tree, options)
        new_xml = etree.tostring(tree).decode()
        self._defineXML(new_xml)

    def set_memory(self, size, flags=0):
        self.instance.setMemoryFlags(size, flags)

    def get_all_qos(self, config=False):
        qos_values = dict()
        tree = etree.fromstring(self._XMLDesc(PERSISTENT_XML if config else 0))
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
        if direction not in ("inbound", "outbound"):
            raise ValueError("Direction must be inbound or outbound")

        average = int(average)
        peak = int(peak)
        burst = int(burst)

        xml = f"<{direction} average='{average}' peak='{peak}' burst='{burst}'/>"

        tree = etree.fromstring(self._XMLDesc(PERSISTENT_XML))

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
                        # keep what the form does not post (an inbound floor)
                        direct.attrib.update(etree.fromstring(xml).attrib)
                    else:
                        band.append(etree.fromstring(xml))
        new_xml = etree.tostring(tree).decode()
        self._defineXML(new_xml)

    def unset_qos(self, mac, direction):
        tree = etree.fromstring(self._XMLDesc(PERSISTENT_XML))
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

        self._defineXML(etree.tostring(tree).decode())

    def add_guest_agent(self):
        channel_xml = """
                        <channel type='unix'>
                            <target type='virtio' name='org.qemu.guest_agent.0'/>
                        </channel>
                      """
        self._attach_device(channel_xml)

    def remove_guest_agent(self):
        for xml_flags, affect in self._definitions():
            tree = etree.fromstring(self._XMLDesc(xml_flags))
            for target in tree.xpath(
                "/domain/devices/channel[@type='unix']/target[@name='org.qemu.guest_agent.0']"
            ):
                channel_xml = etree.tostring(target.getparent()).decode()
                self.instance.detachDeviceFlags(channel_xml, affect)

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

    def set_user_password(self, user, crypted):
        """Set a user's password in the running guest through its agent;
        crypted is a crypt(3) hash."""
        password = base64.b64encode(crypted.encode()).decode()
        agent_command(self.instance, "guest-set-user-password", {"username": user, "password": password, "crypted": True})

    def add_authorized_key(self, user, key):
        """Add an SSH public key to the user's authorized keys in the running
        guest through its agent."""
        agent_command(self.instance, "guest-ssh-add-authorized-keys", {"username": user, "keys": [key], "reset": False})

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
