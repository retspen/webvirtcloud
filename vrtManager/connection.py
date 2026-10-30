import contextlib
import io
import os
import re
import socket
import threading
import time
import uuid
from urllib.parse import quote

import libvirt
from django.conf import settings
from django.utils.functional import cached_property
from libvirt import libvirtError
from lxml import etree
from vrtManager import util
from vrtManager.rwlock import ReadWriteLock

CONN_SOCKET = 4
CONN_TLS = 3
CONN_SSH = 2
CONN_TCP = 1
TLS_PORT = 16514
SSH_PORT = 22
TCP_PORT = 16509

# libvirt has no timeout for opening a connection: an unreachable host
# blocks for the kernel's TCP connect timeout (about 2 minutes), a daemon
# that accepts but never answers blocks forever, and such an open cannot be
# cancelled. Connections are opened in a helper thread, at most one per
# connection at a time, so a stuck host holds one thread and nothing else;
# the caller waits at most CONNECT_TIMEOUT seconds, and a host that failed is
# not tried again for RETRY_AFTER seconds.
CONNECT_TIMEOUT = getattr(settings, "LIBVIRT_CONNECT_TIMEOUT", 5)
RETRY_AFTER = getattr(settings, "LIBVIRT_RETRY_AFTER", 30)
CLOSE_REASONS = {0: "error", 1: "end of file", 2: "keepalive timeout", 3: "client closed"}
# ssh with a connect timeout for qemu+ssh (libvirt runs the "command" binary
# in place of ssh and never passes one itself)
SSH_COMMAND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libvirt-ssh")


class wvmEventLoop(threading.Thread):
    """ Event Loop Class"""

    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}):
        if name is None:
            name = "libvirt event loop"

        super(wvmEventLoop, self).__init__(group, target, name, args, kwargs)

        # we run this thread in deamon mode, so it does
        # not block shutdown of the server
        self.daemon = True

    def run(self):
        while True:
            # if this method will fail it raises libvirtError
            # we do not catch the exception here so it will show up
            # in the logs. Not sure when this call will ever fail
            libvirt.virEventRunDefaultImpl()


# The event loop (keepalive, close callbacks) starts with the first connection
# of a process, not at import: novncd imports this module and then forks a child
# per console, and libvirt must not be used after a fork of a process with
# running libvirt threads. Threads do not survive a fork, so a child starts its
# own loop. This is process state, shared by all connection managers.
_event_loop = {"lock": threading.Lock(), "running": False, "registered": False}


def start_event_loop():
    if _event_loop["running"]:
        return
    with _event_loop["lock"]:
        if _event_loop["running"]:
            return
        if not _event_loop["registered"]:
            # the registration is libvirt's process state and a child inherits it
            libvirt.virEventRegisterDefaultImpl()
            _event_loop["registered"] = True
        wvmEventLoop().start()
        _event_loop["running"] = True


def _after_fork_in_child():
    # the loop thread and any thread holding these locks are gone
    _event_loop["lock"] = threading.Lock()
    _event_loop["running"] = False
    connection_manager.forget_connections()


os.register_at_fork(after_in_child=_after_fork_in_child)


# libvirt's per-host directory of the VMs' UEFI variables (NVRAM)
NVRAM_DIR = "/var/lib/libvirt/qemu/nvram"


class wvmConnection(object):
    """
    class representing a single connection stored in the Connection Manager
    """

    def __init__(self, host, login, passwd, conn):
        """
        Sets all class attributes and tries to open the connection
        """
        # connection lock is used to lock all changes to the connection state attributes
        # (connection and last_error)
        self.connection_state_lock = threading.Lock()
        self.connection = None
        self.last_error = None
        self._opening = None  # threading.Event of the open in progress
        self._retry_at = 0.0  # monotonic time before which no new open is tried

        # credentials
        self.host = host
        self.login = login
        self.passwd = passwd
        self.type = conn

    def connect(self):
        """Open the connection if needed, waiting at most CONNECT_TIMEOUT.
        On failure last_error says why and connected stays False."""
        with self.connection_state_lock:
            if self.connected:
                return
            if self._opening is not None and self._opening.abandoned:
                # A caller already waited for this open in vain; nobody waits
                # again until it ends (one thread per connection, however long).
                return
            if time.monotonic() < self._retry_at:
                return  # failed recently: answer with the last error at once
            if self._opening is None:
                self._opening = threading.Event()
                self._opening.abandoned = False
                threading.Thread(target=self._open, args=(self._opening,), daemon=True).start()
            opening = self._opening

        if not opening.wait(CONNECT_TIMEOUT):
            with self.connection_state_lock:
                if self._opening is opening:  # still running: give up waiting, not the open
                    self.last_error = f"Connection Failed: {self.host} did not answer within {CONNECT_TIMEOUT} s"
                    opening.abandoned = True

    def _open(self, opening):
        """Helper thread: open, configure and publish the connection."""
        connection = error = None
        try:
            connection = self._open_transport()
            if not connection.isAlive():  # closed again before it was published
                raise util.OperationError("the connection closed right after opening")
            # Drivers without keepalive or close callbacks work without them
            try:
                connection.setKeepAlive(connection_manager.keepalive_interval, connection_manager.keepalive_count)
            except libvirtError:
                pass
            try:
                connection.registerCloseCallback(self.__connection_close_callback, None)
            except libvirtError:
                pass
        except Exception as e:  # libvirtError, or anything else from the transport
            error = f"Connection Failed: {str(e)}"
        finally:
            with self.connection_state_lock:
                if error is None:
                    self.connection = connection
                    self.last_error = None
                    self._retry_at = 0.0
                else:
                    self.connection = None
                    self.last_error = error
                    self._retry_at = time.monotonic() + RETRY_AFTER
                self._opening = None
            opening.set()

    def _open_transport(self):
        if self.type == CONN_TCP:
            return self.__connect_tcp()
        if self.type == CONN_SSH:
            return self.__connect_ssh()
        if self.type == CONN_TLS:
            return self.__connect_tls()
        if self.type == CONN_SOCKET:
            return self.__connect_socket()
        raise ValueError(f'"{self.type}" is not a valid connection type')

    def alive_connection(self):
        """The libvirt connection if it is alive, else None. self.connection
        is read once: the close callback can clear it at any moment."""
        connection = self.connection
        try:
            return connection if connection is not None and connection.isAlive() else None
        except libvirtError:
            # isAlive failed for some reason
            return None

    @property
    def connected(self):
        return self.alive_connection() is not None

    def __libvirt_auth_credentials_callback(self, credentials, user_data):
        for credential in credentials:
            if credential[0] == libvirt.VIR_CRED_AUTHNAME:
                credential[4] = self.login
                if len(credential[4]) == 0:
                    credential[4] = credential[3]
            elif credential[0] == libvirt.VIR_CRED_PASSPHRASE:
                credential[4] = self.passwd
            else:
                return -1
        return 0

    def __connection_close_callback(self, connection, reason, opaque=None):
        with self.connection_state_lock:
            # A late callback of a connection that was already replaced must
            # not drop its successor.
            if connection is not self.connection:
                return
            self.last_error = f"Connection closed ({CLOSE_REASONS.get(reason, reason)})"
            # prevent other threads from using the connection (in the future)
            self.connection = None

    def __connect_tcp(self):
        flags = [libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE]
        auth = [flags, self.__libvirt_auth_credentials_callback, None]
        return libvirt.openAuth(f"qemu+tcp://{self.host}/system", auth, 0)

    def __connect_ssh(self):
        return libvirt.open(f"qemu+ssh://{self.login}@{self.host}/system?command={quote(SSH_COMMAND)}")

    def __connect_tls(self):
        flags = [libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE]
        auth = [flags, self.__libvirt_auth_credentials_callback, None]
        return libvirt.openAuth(f"qemu+tls://{self.login}@{self.host}/system", auth, 0)

    def __connect_socket(self):
        return libvirt.open("qemu:///system")

    def close(self):
        """
        closes the connection (if it is active)
        """
        self.connection_state_lock.acquire()
        try:
            if self.connected:
                try:
                    # to-do: handle errors?
                    self.connection.close()
                except libvirtError:
                    pass

            self.connection = None
            self.last_error = None
        finally:
            self.connection_state_lock.release()

    def __del__(self):
        if self.connection is not None:
            # unregister callback (as it is no longer valid if this instance gets deleted)
            try:
                self.connection.unregisterCloseCallback()
            except Exception:
                pass

    def __str__(self):
        if self.type == CONN_TCP:
            type_str = "tcp"
        elif self.type == CONN_SSH:
            type_str = "ssh"
        elif self.type == CONN_TLS:
            type_str = "tls"
        else:
            type_str = "invalid_type"

        return f"qemu+{type_str}://{self.login}@{self.host}/system"

    def __repr__(self):
        return f"<wvmConnection {str(self)}>"


class wvmConnectionManager(object):
    def __init__(self, keepalive_interval=5, keepalive_count=5):
        self.keepalive_interval = keepalive_interval
        self.keepalive_count = keepalive_count

        # connection dict
        # maps hostnames to a list of connection objects for this hostname
        # atm it is possible to create more than one connection per hostname
        # with different logins or auth methods
        # connections are shared between all threads, see:
        #     http://wiki.libvirt.org/page/FAQ#Is_libvirt_thread_safe.3F
        self._connections = dict()
        self._connections_lock = ReadWriteLock()
        self._inherited = []

    def forget_connections(self):
        """For a forked child: stop using the inherited connections (the
        parent's sockets). They are kept, not released: their destructors
        would call libvirt in the child."""
        self._inherited.append(self._connections)
        self._connections = dict()
        self._connections_lock = ReadWriteLock()

    def _search_connection(self, host, login, passwd, conn):
        """
        search the connection dict for a connection with the given credentials
        if it does not exist return None
        """
        self._connections_lock.acquireRead()
        try:
            if host in self._connections:
                connections = self._connections[host]

                for connection in connections:
                    if connection.login == login and connection.passwd == passwd and connection.type == conn:
                        return connection
        finally:
            self._connections_lock.release()

        return None

    def get_connection(self, host, login, passwd, conn):
        """
        returns a connection object (as returned by the libvirt.open* methods) for the given host and credentials
        raises libvirtError if (re)connecting fails
        """
        start_event_loop()
        # force all string values to unicode
        host = str(host)
        login = str(login)
        passwd = str(passwd) if passwd is not None else None

        connection = self._search_connection(host, login, passwd, conn)

        if connection is None:
            self._connections_lock.acquireWrite()
            try:
                # we have to search for the connection again after acquiring the write lock
                # as the thread previously holding the write lock may have already added our connection
                connection = self._search_connection(host, login, passwd, conn)
                if connection is None:
                    # Only register it here: connecting under the global lock
                    # would make every other host wait for a slow one.
                    connection = wvmConnection(host, login, passwd, conn)
                    self._connections.setdefault(host, []).append(connection)
            finally:
                self._connections_lock.release()

        live = connection.alive_connection()
        if live is None:
            # (re-)connect within CONNECT_TIMEOUT; one open per connection at a time
            connection.connect()
            live = connection.alive_connection()
        if live is None:
            raise util.ConnectionFailed(connection.last_error)
        return live

    def host_is_up(self, conn_type, hostname, timeout=1):
        """True if the libvirt endpoint of hostname accepts a TCP (or Unix
        socket) connection. This is a reachability probe only: it does not
        check credentials or libvirt itself. hostname may carry a port
        ("host:port", "[v6]:port")."""
        if conn_type == CONN_SOCKET:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.settimeout(timeout)
                sock.connect("/var/run/libvirt/libvirt-sock")
                return True
            except OSError:
                return False
            finally:
                sock.close()
        default_port = {CONN_SSH: SSH_PORT, CONN_TCP: TCP_PORT, CONN_TLS: TLS_PORT}.get(conn_type)
        if default_port is None:
            return False
        host, port = str(hostname), default_port
        match = re.fullmatch(r"\[?([^\[\]]+?)\]?:(\d+)", host)
        if match and (host.startswith("[") or host.count(":") == 1):
            host, port = match.group(1), int(match.group(2))
        try:
            with socket.create_connection((host.strip("[]"), port), timeout=timeout):
                return True
        except OSError:
            return False

connection_manager = wvmConnectionManager(
    settings.LIBVIRT_KEEPALIVE_INTERVAL if hasattr(settings, "LIBVIRT_KEEPALIVE_INTERVAL") else 5,
    settings.LIBVIRT_KEEPALIVE_COUNT if hasattr(settings, "LIBVIRT_KEEPALIVE_COUNT") else 5,
)


class wvmConnect(object):
    def __init__(self, host, login, passwd, conn):
        self.login = login
        self.host = host
        self.passwd = passwd
        self.conn = conn

        # get connection from connection manager
        self.wvm = connection_manager.get_connection(host, login, passwd, conn)

    def is_qemu(self):
        return self.wvm.getURI().startswith("qemu")

    @cached_property
    def capabilities_xml(self):
        """The host's capabilities, read once per object (a request): most getters below parse them"""
        return self.wvm.getCapabilities()

    def host_uuid(self):
        """The host's UUID (capabilities): compute records of one host share it"""
        return util.get_xml_path(self.capabilities_xml, "/capabilities/host/uuid")

    @cached_property
    def host_info(self):
        """The host's info (architecture, memory in MiB, CPUs, ...), read once per object"""
        return self.wvm.getInfo()

    @cached_property
    def dom_cap_xmls(self):
        """The domain capabilities read so far, by emulator, arch, machine and domain type"""
        return {}

    def get_cap_xml(self):
        """Return xml capabilities"""
        return self.capabilities_xml

    def get_dom_cap_xml(self, arch, machine):
        """ Return domain capabilities xml"""
        emulatorbin = self.get_emulator(arch)
        virttype = "kvm" if "kvm" in self.get_hypervisors_domain_types()[arch] else "qemu"

        machine_types = self.get_machine_types(arch)
        if not machine or machine not in machine_types:
            machine = "pc" if "pc" in machine_types else machine_types[0]
        key = (emulatorbin, arch, machine, virttype)
        if key not in self.dom_cap_xmls:
            self.dom_cap_xmls[key] = self.wvm.getDomainCapabilities(*key)
        return self.dom_cap_xmls[key]

    def get_capabilities(self, arch):
        """ Host Capabilities for specified architecture """

        def guests(ctx):
            result = dict()
            for arch_el in ctx.xpath("/capabilities/guest/arch[@name=$arch]", arch=arch):
                result["wordsize"] = arch_el.find("wordsize").text
                result["emulator"] = arch_el.find("emulator").text
                result["domain"] = [v for v in arch_el.xpath("domain/@type")]

                result["machines"] = []
                for m in arch_el.xpath("machine"):
                    result["machines"].append(
                        {"machine": m.text, "max_cpu": m.get("maxCpus"), "canonical": m.get("canonical")}
                    )

                guest_el = arch_el.getparent()
                for f in guest_el.xpath("features"):
                    result["features"] = [t.tag for t in f.getchildren()]

                result["os_type"] = guest_el.find("os_type").text

            return result

        return util.get_xml_path(self.get_cap_xml(), func=guests)

    def get_dom_capabilities(self, arch, machine):
        """Return domain capabilities"""
        result = dict()

        xml = self.get_dom_cap_xml(arch, machine)
        result["path"] = util.get_xml_path(xml, "/domainCapabilities/path")
        result["domain"] = util.get_xml_path(xml, "/domainCapabilities/domain")
        result["machine"] = util.get_xml_path(xml, "/domainCapabilities/machine")
        result["vcpu_max"] = util.get_xml_path(xml, "/domainCapabilities/vcpu/@max")
        result["iothreads_support"] = util.get_xml_path(xml, "/domainCapabilities/iothreads/@supported")
        result["os_support"] = util.get_xml_path(xml, "/domainCapabilities/os/@supported")

        result["loader_support"] = util.get_xml_path(xml, "/domainCapabilities/os/loader/@supported")
        if result["loader_support"] == "yes":
            result["loaders"] = self.get_os_loaders(arch, machine)
            result["loader_enums"] = self.get_os_loader_enums(arch, machine)

        result["cpu_modes"] = self.get_cpu_modes(arch, machine)
        if "custom" in result["cpu_modes"]:
            # supported and unknown cpu models
            result["cpu_custom_models"] = self.get_cpu_custom_types(arch, machine)

        result["disk_support"] = util.get_xml_path(xml, "/domainCapabilities/devices/disk/@supported")
        if result["disk_support"] == "yes":
            result["disk_devices"] = self.get_disk_device_types(arch, machine)
            result["disk_bus"] = self.get_disk_bus_types(arch, machine)

        result["video_support"] = util.get_xml_path(xml, "/domainCapabilities/devices/video/@supported")
        if result["video_support"] == "yes":
            result["video_types"] = self.get_video_models(arch, machine)

        result["hostdev_support"] = util.get_xml_path(xml, "/domainCapabilities/devices/hostdev/@supported")
        if result["hostdev_support"] == "yes":
            result["hostdev_types"] = self.get_hostdev_modes(arch, machine)
            result["hostdev_startup_policies"] = self.get_hostdev_startup_policies(arch, machine)
            result["hostdev_subsys_types"] = self.get_hostdev_subsys_types(arch, machine)

        result["features_gic_support"] = util.get_xml_path(xml, "/domainCapabilities/features/gic/@supported")
        result["features_genid_support"] = util.get_xml_path(xml, "/domainCapabilities/features/genid/@supported")
        result["features_vmcoreinfo_support"] = util.get_xml_path(
            xml, "/domainCapabilities/features/vmcoreinfo/@supported"
        )
        result["features_sev_support"] = util.get_xml_path(xml, "/domainCapabilities/features/sev/@supported")

        return result

    def get_version(self):
        """
        :return: libvirt version
        """
        ver = self.wvm.getVersion()
        major = ver // 1000000
        ver = ver % 1000000
        minor = ver // 1000
        ver = ver % 1000
        release = ver
        return f"{major}.{minor}.{release}"

    def get_lib_version(self):
        ver = self.wvm.getLibVersion()
        major = ver // 1000000
        ver %= 1000000
        minor = ver // 1000
        ver %= 1000
        release = ver
        return f"{major}.{minor}.{release}"

    def is_kvm_supported(self):
        """
        :return: kvm support or not
        """
        return util.is_kvm_available(self.get_cap_xml())

    def get_storages(self, only_actives=False):
        """
        :return: list of active or all storages
        """
        storages = []
        for pool in self.wvm.listStoragePools():
            storages.append(pool)
        if not only_actives:
            for pool in self.wvm.listDefinedStoragePools():
                storages.append(pool)
        return storages

    def get_networks(self):
        """
        :return: list of host networks
        """
        virtnet = []
        for net in self.wvm.listNetworks():
            virtnet.append(net)
        for net in self.wvm.listDefinedNetworks():
            virtnet.append(net)
        return virtnet

    def get_ifaces(self):
        """The names of the host's interfaces, in every state."""
        return [iface.name() for iface in self.wvm.listAllInterfaces(0)]

    def get_nwfilters(self):
        """
        :return: list of network filters
        """
        nwfilters = []
        for nwfilter in self.wvm.listNWFilters():
            nwfilters.append(nwfilter)
        return nwfilters

    def get_cache_modes(self):
        """
        :return: Get cache available modes
        """
        return {
            "default": "Default",
            "none": "Disabled",
            "writethrough": "Write through",
            "writeback": "Write back",
            "directsync": "Direct sync",  # since libvirt 0.9.5
            "unsafe": "Unsafe",  # since libvirt 0.9.7
        }

    def get_io_modes(self):
        """
        :return: available io modes
        """
        return {
            "default": "Default",
            "native": "Native",
            "threads": "Threads",
        }

    def get_discard_modes(self):
        """
        :return: available discard modes
        """
        return {
            "default": "Default",
            "ignore": "Ignore",
            "unmap": "Unmap",
        }

    def get_detect_zeroes_modes(self):
        """
        :return: available detect zeroes modes
        """
        return {
            "default": "Default",
            "on": "On",
            "off": "Off",
            "unmap": "Unmap",
        }

    def get_hypervisors_domain_types(self):
        """
        :return: hypervisor domain types
        """

        def hypervisors(ctx):
            result = {}
            for arch in ctx.xpath("/capabilities/guest/arch"):
                domain_types = arch.xpath("domain/@type")
                arch_name = arch.xpath("@name")[0]
                result[arch_name] = domain_types
            return result

        return util.get_xml_path(self.get_cap_xml(), func=hypervisors)

    def get_hypervisors_machines(self):
        """
        :return: hypervisor and its machine types
        """

        def machines(ctx):
            result = dict()
            for arche in ctx.xpath("/capabilities/guest/arch"):
                arch = arche.get("name")

                result[arch] = self.get_machine_types(arch)
            return result

        return util.get_xml_path(self.get_cap_xml(), func=machines)

    def get_emulator(self, arch):
        """
        :return: emulator list
        """
        # arch comes from the URL: an XPath variable, not part of the expression
        def emulator(ctx):
            found = ctx.xpath("/capabilities/guest/arch[@name=$arch]/emulator", arch=arch)
            return found[0].text if found else None

        return util.get_xml_path(self.get_cap_xml(), func=emulator)

    def get_machine_types(self, arch):
        """
        :return: canonical(if exist) name of machine types
        """

        def machines(ctx):
            result = list()
            canonical_name = ctx.xpath("/capabilities/guest/arch[@name=$arch]/machine[@canonical]", arch=arch)
            if not canonical_name:
                canonical_name = ctx.xpath("/capabilities/guest/arch[@name=$arch]/machine", arch=arch)
            for archi in canonical_name:
                result.append(archi.text)
            return result

        return util.get_xml_path(self.get_cap_xml(), func=machines)

    def get_emulators(self):
        """
        :return: host emulators list
        """

        def emulators(ctx):
            result = {}
            for arch in ctx.xpath("/capabilities/guest/arch"):
                emulator = arch.xpath("emulator")
                arch_name = arch.xpath("@name")[0]
                result[arch_name] = emulator
            return result

        return util.get_xml_path(self.get_cap_xml(), func=emulators)

    def get_os_loaders(self, arch="x86_64", machine="pc"):
        """
        :param arch: architecture
        :param machine:
        :return: available os loaders list
        """

        def get_os_loaders(ctx):
            return [v.text for v in ctx.xpath("/domainCapabilities/os/loader[@supported='yes']/value")]

        return util.get_xml_path(self.get_dom_cap_xml(arch, machine), func=get_os_loaders)

    def get_os_loader_enums(self, arch, machine):
        """
        :param arch: architecture
        :param machine:
        :return: available os loaders list
        """

        def get_os_loader_enums(ctx):
            result = dict()
            enums = [v for v in ctx.xpath("/domainCapabilities/os/loader[@supported='yes']/enum/@name")]
            for enum in enums:
                path = "/domainCapabilities/os/loader[@supported='yes']/enum[@name='{}']/value".format(enum)
                result[enum] = [v.text for v in ctx.xpath(path)]
            return result

        return util.get_xml_path(self.get_dom_cap_xml(arch, machine), func=get_os_loader_enums)

    def get_disk_bus_types(self, arch, machine):
        """
        :param machine:
        :param arch:
        :return: available disk bus types list
        """

        def get_bus_list(ctx):
            return [v.text for v in ctx.xpath("/domainCapabilities/devices/disk/enum[@name='bus']/value")]

        # return [ 'ide', 'scsi', 'usb', 'virtio' ]
        return util.get_xml_path(self.get_dom_cap_xml(arch, machine), func=get_bus_list)

    def get_disk_device_types(self, arch, machine):
        """
        :param arch: architecture
        :param machine:
        :return: available disk device type list
        """

        def get_device_list(ctx):
            return [v.text for v in ctx.xpath("/domainCapabilities/devices/disk/enum[@name='diskDevice']/value")]

        # return [ 'disk', 'cdrom', 'floppy', 'lun' ]
        return util.get_xml_path(self.get_dom_cap_xml(arch, machine), func=get_device_list)

    def get_cpu_modes(self, arch, machine):
        """
        :param arch: architecture
        :param machine:
        :return: available cpu modes
        """

        def get_cpu_modes(ctx):
            return [v for v in ctx.xpath("/domainCapabilities/cpu/mode[@supported='yes']/@name")]

        return util.get_xml_path(self.get_dom_cap_xml(arch, machine), func=get_cpu_modes)

    def get_cpu_custom_types(self, arch, machine):
        """
        :param arch: architecture
        :param machine:
        :return: available graphics types
        """

        def get_custom_list(ctx):
            usable_yes = "/domainCapabilities/cpu/mode[@name='custom'][@supported='yes']/model[@usable='yes']"
            usable_unknown = "/domainCapabilities/cpu/mode[@name='custom'][@supported='yes']/model[@usable='unknown']"
            result = [v.text for v in ctx.xpath(usable_yes)]
            result += [v.text for v in ctx.xpath(usable_unknown)]
            return result

        return util.get_xml_path(self.get_dom_cap_xml(arch, machine), func=get_custom_list)

    def get_hostdev_modes(self, arch, machine):
        """
        :param arch: architecture
        :param machine:
        :return. available nodedev modes
        """

        def get_hostdev_list(ctx):
            return [v.text for v in ctx.xpath("/domainCapabilities/devices/hostdev/enum[@name='mode']/value")]

        return util.get_xml_path(self.get_dom_cap_xml(arch, machine), func=get_hostdev_list)

    def get_hostdev_startup_policies(self, arch, machine):
        """
        :param arch: architecture
        :param machine:
        :return: available hostdev modes
        """

        def get_hostdev_list(ctx):
            return [v.text for v in ctx.xpath("/domainCapabilities/devices/hostdev/enum[@name='startupPolicy']/value")]

        return util.get_xml_path(self.get_dom_cap_xml(arch, machine), func=get_hostdev_list)

    def get_hostdev_subsys_types(self, arch, machine):
        """
        :param arch: architecture
        :param machine:
        :return: available nodedev sub system types
        """

        def get_hostdev_list(ctx):
            return [v.text for v in ctx.xpath("/domainCapabilities/devices/hostdev/enum[@name='subsysType']/value")]

        return util.get_xml_path(self.get_dom_cap_xml(arch, machine), func=get_hostdev_list)

    def get_network_models(self):
        """
        :return: network card models
        """
        return ["default", "e1000", "e1000e", "rtl8139", "virtio"]

    def get_image_formats(self):
        """
        :return: available image formats
        """
        return ["raw", "qcow", "qcow2"]

    def get_file_extensions(self):
        """
        :return: available image filename extensions
        """
        return ["img", "qcow", "qcow2"]

    def get_video_models(self, arch, machine):
        """
        :param arch: architecture
        :param machine:
        :return: available graphics video types
        """

        def get_video_list(ctx):
            result = []
            for video_enum in ctx.xpath("/domainCapabilities/devices/video/enum"):
                if video_enum.xpath("@name")[0] == "modelType":
                    for values in video_enum:
                        result.append(values.text)
            return result

        return util.get_xml_path(self.get_dom_cap_xml(arch, machine), func=get_video_list)

    def get_iface(self, name):
        return self.wvm.interfaceLookupByName(name)

    def get_secrets_info(self):
        """Every secret of the host: UUID, usage type and usage (a volume
        path, an iSCSI target, a Ceph or TLS or vTPM name), whether it is
        ephemeral and private. One listing, one XML read per secret; a secret
        gone meanwhile is left out."""
        secrets = []
        for secret in self.wvm.listAllSecrets(0):
            try:
                tree = etree.fromstring(secret.XMLDesc(0))
            except libvirtError as err:
                if err.get_error_code() != libvirt.VIR_ERR_NO_SECRET:
                    raise
                continue
            secrets.append({
                "uuid": secret.UUIDString(),
                "usage_type": tree.xpath("string(usage/@type)") or "none",
                "usage": tree.xpath("string(usage/*)"),
                "ephemeral": tree.get("ephemeral") == "yes",
                "private": tree.get("private") == "yes",
            })
        return sorted(secrets, key=lambda secret: (secret["usage_type"], secret["usage"]))

    def get_storage(self, name):
        return self.wvm.storagePoolLookupByName(name)

    def get_volume_by_path(self, path):
        return self.wvm.storageVolLookupByPath(path)

    def remove_nvram(self, path, destination):
        """Deletes the NVRAM file of a VM that migrated from this host to
        destination (a wvmConnect). Only a file in libvirt's per-host NVRAM
        directory, and only when destination does not see that directory too
        (shared storage would hold the migrated VM's own file). Returns
        whether a file was deleted."""
        if os.path.dirname(path) != NVRAM_DIR:
            return False
        with self._nvram_pool() as pool, destination._nvram_pool() as other:
            try:
                if self.same_directory(pool, other):
                    return False
            except libvirtError:
                return False  # not known to be the source's own file
            vol = self._find_volume(pool, os.path.basename(path))
            if vol is None:
                return False
            vol.delete(0)
            return True

    @staticmethod
    def same_directory(pool, other):
        """Whether pools of two hosts are one directory: creating the same
        file in both fails then, as it exists already. The create is
        exclusive on the file server, unlike a directory listing, which an
        NFS client may cache. Any other failure raises: it tells nothing."""
        marker = (
            f"<volume><name>webvirtcloud-check-{uuid.uuid4().hex}</name><capacity>0</capacity>"
            "<target><format type='raw'/></target></volume>"
        )
        mine = pool.createXML(marker, 0)
        try:
            other.createXML(marker, 0).delete(0)
        except libvirtError as error:
            # the file exists (OPERATION_INVALID), or the pool lists it already
            if error.get_error_code() in (libvirt.VIR_ERR_OPERATION_INVALID, libvirt.VIR_ERR_STORAGE_VOL_EXIST):
                return True
            raise
        finally:
            mine.delete(0)
        return False

    def pool_at(self, directory):
        """The active pool whose directory is directory, or None. A pool
        without a target path (rbd, gluster, ...) holds no files."""
        for pool in self.wvm.listAllStoragePools(libvirt.VIR_CONNECT_LIST_STORAGE_POOLS_ACTIVE):
            if (util.get_xml_path(pool.XMLDesc(0), "/pool/target/path") or "").rstrip("/") == directory:
                return pool
        return None

    def file_pools(self):
        """The active pools of this host that keep disks as files, a copy's
        destination: {name: (pool, directory)}."""
        pools = {}
        for pool in self.wvm.listAllStoragePools(libvirt.VIR_CONNECT_LIST_STORAGE_POOLS_ACTIVE):
            tree = etree.fromstring(pool.XMLDesc(0))
            if tree.get("type") in ("dir", "fs", "netfs") and tree.findtext("target/path"):
                pools[pool.name()] = (pool, tree.findtext("target/path").rstrip("/"))
        return pools

    @contextlib.contextmanager
    def _nvram_pool(self):
        """An active, refreshed pool on NVRAM_DIR: libvirt reads and deletes
        files only as volumes of a pool. A transient one when none exists."""
        pool = self.pool_at(NVRAM_DIR)
        if pool is not None:
            pool.refresh(0)
            yield pool
            return
        pool = self.wvm.storagePoolCreateXML(
            f"<pool type='dir'><name>webvirtcloud-nvram-{uuid.uuid4().hex[:8]}</name>"
            f"<target><path>{NVRAM_DIR}</path></target></pool>",
            0,
        )
        try:
            yield pool
        finally:
            # a transient pool left by a failed destroy goes with libvirtd's next restart
            with contextlib.suppress(libvirtError):
                pool.destroy()

    def upload_volume(self, pool, name, data):
        """A new raw volume in pool holding data, written through a libvirt
        stream, which every connection type carries. A failed write leaves
        no volume."""
        vol = pool.createXML(
            f"<volume><name>{util.xml_escape(name)}</name><capacity>{len(data)}</capacity>"
            "<target><format type='raw'/></target></volume>",
            0,
        )
        try:
            stream = self.wvm.newStream(0)
            vol.upload(stream, 0, len(data), 0)
            stream.sendAll(lambda _stream, size, buffer: buffer.read(size), io.BytesIO(data))
            stream.finish()
        except Exception:
            vol.delete(0)
            raise
        return vol

    @staticmethod
    def _find_volume(pool, name):
        try:
            return pool.storageVolLookupByName(name)
        except libvirtError as err:
            if err.get_error_code() == libvirt.VIR_ERR_NO_STORAGE_VOL:
                return None
            raise

    def get_network(self, net):
        return self.wvm.networkLookupByName(net)

    def get_network_forward(self, net_name):
        def get_forward(doc):
            forward_mode = util.get_xpath(doc, "/network/forward/@mode")
            return forward_mode or "isolated"

        net = self.get_network(net_name)
        xml = net.XMLDesc(0)
        return util.get_xml_path(xml, func=get_forward)

    def get_nwfilter(self, name):
        return self.wvm.nwfilterLookupByName(name)

    def get_instance(self, name):
        return self.wvm.lookupByName(name)

    def get_instances(self):
        instances = []
        for inst_id in self.wvm.listDomainsID():
            dom = self.wvm.lookupByID(int(inst_id))
            instances.append(dom.name())
        for name in self.wvm.listDefinedDomains():
            instances.append(name)
        return instances

    def domain_trees(self, running_only=False):
        """Each domain's name with its definitions, parsed: the live one, and
        for a persistent domain the one saved for its next boot too, read
        whether it runs or not (it may stop meanwhile); with running_only the
        live one of each running domain. A domain gone meanwhile is left out."""
        listing = libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE if running_only else 0
        for dom in self.wvm.listAllDomains(listing):
            try:
                xmls = [dom.XMLDesc(0)]
                if not running_only and dom.isPersistent():
                    xmls.append(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
            except libvirtError as err:
                if err.get_error_code() != libvirt.VIR_ERR_NO_DOMAIN:
                    raise
                continue
            yield dom.name(), [etree.fromstring(xml) for xml in xmls]

    def domains_using(self, match, running_only=False):
        """Names of the domains with a definition (domain_trees) that
        match(tree) holds for."""
        return sorted(name for name, trees in self.domain_trees(running_only) if any(map(match, trees)))

    def paths_in_use(self, skip_uuid=None, own=()):
        """Paths (names for network disks) a domain uses as a disk or a
        backing file of one, or as a file of its snapshots (overlays, memory,
        the disks they were taken on); and the backing files of volumes.
        skip_uuid leaves out one domain, own the volumes whose backing files
        do not count."""
        used = set()
        for dom in self.wvm.listAllDomains():
            if dom.UUIDString() == skip_uuid:
                continue
            for flags in (0, libvirt.VIR_DOMAIN_XML_INACTIVE):
                used.update(self._source_paths(etree.fromstring(dom.XMLDesc(flags))))
            for snap in dom.listAllSnapshots(0):
                tree = etree.fromstring(snap.getXMLDesc(0))
                used.update(tree.xpath("disks/disk/source/@file|memory/@file"))
                for saved in tree.xpath("domain|inactiveDomain"):
                    used.update(self._source_paths(saved))
        # A stopped domain's XML has no backing chain; the volumes have it.
        # Any volume backed by a path keeps that path, even an unattached one.
        for pool in self.wvm.listAllStoragePools():
            if not pool.isActive():
                continue
            with contextlib.suppress(libvirtError):
                pool.refresh(0)
            for vol in pool.listAllVolumes():
                # only a volume removed meanwhile is skipped: one that cannot
                # be read may still keep a backing file
                try:
                    if vol.path() not in own:
                        used.update(etree.fromstring(vol.XMLDesc(0)).xpath("./backingStore/path/text()"))
                except libvirtError as err:
                    if err.get_error_code() != libvirt.VIR_ERR_NO_STORAGE_VOL:
                        raise
        return used

    def _source_paths(self, domain):
        """The files, devices or network names of a domain definition's
        disks and of their backing chains ("//" reaches a running domain's
        backingStore); a pool volume source as its volume's path."""
        paths = []
        for source in domain.xpath("devices/disk//source"):
            if source.get("pool") and source.get("volume"):
                try:
                    pool = self.wvm.storagePoolLookupByName(source.get("pool"))
                    paths.append(pool.storageVolLookupByName(source.get("volume")).path())
                except libvirtError as err:
                    # a volume that is not there cannot be the one deleted
                    if err.get_error_code() not in (libvirt.VIR_ERR_NO_STORAGE_VOL, libvirt.VIR_ERR_NO_STORAGE_POOL):
                        raise
            else:
                paths += [v for v in (source.get("file"), source.get("dev"), source.get("name")) if v]
        return paths

    def get_snapshots(self):
        instance = []
        for snap_id in self.wvm.listDomainsID():
            dom = self.wvm.lookupByID(int(snap_id))
            if dom.snapshotNum(0) != 0:
                instance.append(dom.name())
        for name in self.wvm.listDefinedDomains():
            dom = self.wvm.lookupByName(name)
            if dom.snapshotNum(0) != 0:
                instance.append(dom.name())
        return instance

    def can_change_interfaces(self):
        """Whether the host's libvirt can define interfaces: the udev backend
        only reads them. The definition sent is invalid, so nothing is
        defined: a backend without define refuses it as unsupported, one with
        define as bad XML. Any other refusal, of the connection say, is not an
        answer and is raised; one the host's access rules give is a no."""
        try:
            self.wvm.interfaceDefineXML("<interface/>", 0)
        except libvirtError as err:
            if err.get_error_code() in (libvirt.VIR_ERR_NO_SUPPORT, libvirt.VIR_ERR_OPERATION_DENIED):
                return False
            if err.get_error_code() in (libvirt.VIR_ERR_XML_ERROR, libvirt.VIR_ERR_XML_DETAIL):
                return True
            raise
        return True

    def get_net_devices(self):
        """The host's network interface names; libvirt lists only the network devices"""
        return [
            util.get_xml_path(dev.XMLDesc(0), "/device/capability/interface")
            for dev in self.wvm.listAllDevices(libvirt.VIR_CONNECT_LIST_NODE_DEVICES_CAP_NET)
        ]

    def get_host_instances(self, raw_mem_size=False):
        vname = {}

        def get_info(doc):
            mem = util.get_xpath(doc, "/domain/currentMemory")
            mem = int(mem) // 1024
            if raw_mem_size:
                mem = int(mem) * (1024 * 1024)
            cur_vcpu = util.get_xpath(doc, "/domain/vcpu/@current")
            if cur_vcpu:
                vcpu = cur_vcpu
            else:
                vcpu = util.get_xpath(doc, "/domain/vcpu")
            title = util.get_xpath(doc, "/domain/title")
            title = title if title else ""
            description = util.get_xpath(doc, "/domain/description")
            description = description if description else ""
            return mem, vcpu, title, description

        for name in self.get_instances():
            dom = self.get_instance(name)
            xml = dom.XMLDesc(0)
            (mem, vcpu, title, description) = util.get_xml_path(xml, func=get_info)
            vname[dom.name()] = {
                "status": dom.info()[0],
                "uuid": dom.UUIDString(),
                "vcpu": vcpu,
                "memory": mem,
                "title": title,
                "description": description,
            }
        return vname

    def get_user_instances(self, name):
        dom = self.get_instance(name)
        xml = dom.XMLDesc(0)

        def get_info(ctx):
            mem = util.get_xpath(ctx, "/domain/currentMemory")
            mem = int(mem) // 1024
            cur_vcpu = util.get_xpath(ctx, "/domain/vcpu/@current")
            if cur_vcpu:
                vcpu = cur_vcpu
            else:
                vcpu = util.get_xpath(ctx, "/domain/vcpu")
            title = util.get_xpath(ctx, "/domain/title")
            title = title if title else ""
            description = util.get_xpath(ctx, "/domain/description")
            description = description if description else ""
            return mem, vcpu, title, description

        (mem, vcpu, title, description) = util.get_xml_path(xml, func=get_info)
        return {
            "name": dom.name(),
            "status": dom.info()[0],
            "uuid": dom.UUIDString(),
            "vcpu": vcpu,
            "memory": mem,
            "title": title,
            "description": description,
        }

    def close(self):
        """Close connection"""
        # to-do: do not close connection ;)
        # self.wvm.close()
        pass

    def find_uefi_path_for_arch(self, arch, machine):
        """
        Search the loader paths for one that matches the passed arch
        """
        if not self.arch_can_uefi(arch):
            return

        loaders = self.get_os_loaders(arch, machine)
        patterns = util.UEFI_ARCH_PATTERNS.get(arch)
        for pattern in patterns:
            for path in loaders:
                if re.match(pattern, path):
                    return path

    def label_for_firmware_path(self, arch, path):
        """
        Return a pretty label for passed path, based on if we know
        about it or not
        """
        if not path:
            if arch in ["i686", "x86_64"]:
                return "BIOS"
            return

        for arch, patterns in util.UEFI_ARCH_PATTERNS.items():
            for pattern in patterns:
                if re.match(pattern, path):
                    return "UEFI %(arch)s: %(path)s" % {"arch": arch, "path": path}

        return "Custom: %(path)s" % {"path": path}

    def arch_can_uefi(self, arch):
        """
        Return True if we know how to setup UEFI for the passed arch
        """
        return arch in list(util.UEFI_ARCH_PATTERNS.keys())

    def supports_uefi_xml(self, loader_enums):
        """
        Return True if libvirt advertises support for proper UEFI setup
        """
        return "readonly" in loader_enums and "yes" in loader_enums.get("readonly")

    def is_supports_virtio(self, arch, machine):
        if not self.is_qemu():
            return False

        # These _only_ support virtio so don't check the OS
        if arch in ["aarch64", "armv7l", "ppc64", "ppc64le", "s390x", "riscv64", "riscv32"] and machine in [
            "virt",
            "pseries",
        ]:
            return True

        if arch in ["x86_64", "i686"]:
            return True

        return False
