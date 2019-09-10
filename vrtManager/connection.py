import libvirt
import threading
import socket
from vrtManager import util
from vrtManager.rwlock import ReadWriteLock
from django.conf import settings
from libvirt import libvirtError


CONN_SOCKET = 4
CONN_TLS = 3
CONN_SSH = 2
CONN_TCP = 1
TLS_PORT = 16514
SSH_PORT = 22
TCP_PORT = 16509


class wvmEventLoop(threading.Thread):
    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}):
        # register the default event implementation
        # of libvirt, as we do not have an existing
        # event loop.
        libvirt.virEventRegisterDefaultImpl()

        if name is None:
            name = 'libvirt event loop'

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


class wvmConnection(object):
    """
    class representing a single connection stored in the Connection Manager
    # to-do: may also need some locking to ensure to not connect simultaniously in 2 threads
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

        # credentials
        self.host = host
        self.login = login
        self.passwd = passwd
        self.type = conn

        # connect
        self.connect()

    def connect(self):
        self.connection_state_lock.acquire()
        try:
            # recheck if we have a connection (it may have been
            if not self.connected:
                if self.type == CONN_TCP:
                    self.__connect_tcp()
                elif self.type == CONN_SSH:
                    self.__connect_ssh()
                elif self.type == CONN_TLS:
                    self.__connect_tls()
                elif self.type == CONN_SOCKET:
                    self.__connect_socket()
                else:
                    raise ValueError('"{type}" is not a valid connection type'.format(type=self.type))

                if self.connected:
                    # do some preprocessing of the connection:
                    #     * set keep alive interval
                    #     * set connection close/fail handler
                    try:
                        self.connection.setKeepAlive(connection_manager.keepalive_interval, connection_manager.keepalive_count)
                        try:
                            self.connection.registerCloseCallback(self.__connection_close_callback, None)
                        except:
                            # Temporary fix for libvirt > libvirt-0.10.2-41
                            pass
                    except libvirtError as e:
                        # hypervisor driver does not seem to support persistent connections
                        self.last_error = str(e)
        finally:
            self.connection_state_lock.release()

    @property
    def connected(self):
        try:
            return self.connection is not None and self.connection.isAlive()
        except libvirtError:
            # isAlive failed for some reason
            return False

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
        self.connection_state_lock.acquire()
        try:
            # on server shutdown libvirt module gets freed before the close callbacks are called
            # so we just check here if it is still present
            if libvirt is not None:
                if (reason == libvirt.VIR_CONNECT_CLOSE_REASON_ERROR):
                    self.last_error = 'connection closed: Misc I/O error'
                elif (reason == libvirt.VIR_CONNECT_CLOSE_REASON_EOF):
                    self.last_error = 'connection closed: End-of-file from server'
                elif (reason == libvirt.VIR_CONNECT_CLOSE_REASON_KEEPALIVE):
                    self.last_error = 'connection closed: Keepalive timer triggered'
                elif (reason == libvirt.VIR_CONNECT_CLOSE_REASON_CLIENT):
                    self.last_error = 'connection closed: Client requested it'
                else:
                    self.last_error = 'connection closed: Unknown error'

            # prevent other threads from using the connection (in the future)
            self.connection = None
        finally:
            self.connection_state_lock.release()

    def __connect_tcp(self):
        flags = [libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE]
        auth = [flags, self.__libvirt_auth_credentials_callback, None]
        uri = 'qemu+tcp://%s/system' % self.host

        try:
            self.connection = libvirt.openAuth(uri, auth, 0)
            self.last_error = None

        except libvirtError as e:
            self.last_error = 'Connection Failed: ' + str(e)
            self.connection = None

    def __connect_ssh(self):
        uri = 'qemu+ssh://%s@%s/system' % (self.login, self.host)

        try:
            self.connection = libvirt.open(uri)
            self.last_error = None

        except libvirtError as e:
            self.last_error = 'Connection Failed: ' + str(e) + ' --- ' + repr(libvirt.virGetLastError())
            self.connection = None

    def __connect_tls(self):
        flags = [libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE]
        auth = [flags, self.__libvirt_auth_credentials_callback, None]
        uri = 'qemu+tls://%s@%s/system' % (self.login, self.host)

        try:
            self.connection = libvirt.openAuth(uri, auth, 0)
            self.last_error = None

        except libvirtError as e:
            self.last_error = 'Connection Failed: ' + str(e)
            self.connection = None

    def __connect_socket(self):
        uri = 'qemu:///system'

        try:
            self.connection = libvirt.open(uri)
            self.last_error = None

        except libvirtError as e:
            self.last_error = 'Connection Failed: ' + str(e)
            self.connection = None

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
            except:
                pass

    def __unicode__(self):
        if self.type == CONN_TCP:
            type_str = u'tcp'
        elif self.type == CONN_SSH:
            type_str = u'ssh'
        elif self.type == CONN_TLS:
            type_str = u'tls'
        else:
            type_str = u'invalid_type'

        return u'qemu+{type}://{user}@{host}/system'.format(type=type_str, user=self.login, host=self.host)

    def __repr__(self):
        return '<wvmConnection {connection_str}>'.format(connection_str=unicode(self))


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

        # start event loop to handle keepalive requests and other events
        self._event_loop = wvmEventLoop()
        self._event_loop.start()

    def _search_connection(self, host, login, passwd, conn):
        """
        search the connection dict for a connection with the given credentials
        if it does not exist return None
        """
        self._connections_lock.acquireRead()
        try:
            if (host in self._connections):
                connections = self._connections[host]

                for connection in connections:
                    if (connection.login == login and connection.passwd == passwd and connection.type == conn):
                        return connection
        finally:
            self._connections_lock.release()

        return None

    def get_connection(self, host, login, passwd, conn):
        """
        returns a connection object (as returned by the libvirt.open* methods) for the given host and credentials
        raises libvirtError if (re)connecting fails
        """
        # force all string values to unicode
        host = unicode(host)
        login = unicode(login)
        passwd = unicode(passwd) if passwd is not None else None

        connection = self._search_connection(host, login, passwd, conn)

        if (connection is None):
            self._connections_lock.acquireWrite()
            try:
                # we have to search for the connection again after aquireing the write lock
                # as the thread previously holding the write lock may have already added our connection
                connection = self._search_connection(host, login, passwd, conn)
                if (connection is None):
                    # create a new connection if a matching connection does not already exist
                    connection = wvmConnection(host, login, passwd, conn)

                    # add new connection to connection dict
                    if host in self._connections:
                        self._connections[host].append(connection)
                    else:
                        self._connections[host] = [connection]
            finally:
                self._connections_lock.release()

        elif not connection.connected:
            # try to (re-)connect if connection is closed
            connection.connect()

        if connection.connected:
            # return libvirt connection object
            return connection.connection
        else:
            # raise libvirt error
            raise libvirtError(connection.last_error)

    def host_is_up(self, conn_type, hostname):
        """
        returns True if the given host is up and we are able to establish
        a connection using the given credentials.
        """
        try:
            socket_host = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_host.settimeout(1)
            if conn_type == CONN_SSH:
                if ':' in hostname:
                    LIBVIRT_HOST, PORT = (hostname).split(":")
                    PORT = int(PORT)
                else:
                    PORT = SSH_PORT
                    LIBVIRT_HOST = hostname
                socket_host.connect((LIBVIRT_HOST, PORT))
            if conn_type == CONN_TCP:
                socket_host.connect((hostname, TCP_PORT))
            if conn_type == CONN_TLS:
                socket_host.connect((hostname, TLS_PORT))
            socket_host.close()
            return True
        except Exception as err:
            return err

connection_manager = wvmConnectionManager(
    settings.LIBVIRT_KEEPALIVE_INTERVAL if hasattr(settings, 'LIBVIRT_KEEPALIVE_INTERVAL') else 5,
    settings.LIBVIRT_KEEPALIVE_COUNT if hasattr(settings, 'LIBVIRT_KEEPALIVE_COUNT') else 5
)


class wvmConnect(object):
    def __init__(self, host, login, passwd, conn):
        self.login = login
        self.host = host
        self.passwd = passwd
        self.conn = conn

        # get connection from connection manager
        self.wvm = connection_manager.get_connection(host, login, passwd, conn)

    def get_cap_xml(self):
        """Return xml capabilities"""
        return self.wvm.getCapabilities()

    def get_dom_cap_xml(self):
        """ Return domcapabilities xml"""

        arch = self.wvm.getInfo()[0]
        machine = self.get_machines(arch)
        emulatorbin = self.get_emulator(arch)
        virttype = self.hypervisor_type()[arch][0]
        return self.wvm.getDomainCapabilities(emulatorbin, arch, machine, virttype)

    def get_version(self):
        ver = self.wvm.getVersion()
        major = ver / 1000000
        ver = ver % 1000000
        minor = ver / 1000
        ver = ver % 1000
        release = ver
        return "%s.%s.%s" % (major,minor,release)

    def get_lib_version(self):
        ver = self.wvm.getLibVersion()
        major = ver / 1000000
        ver %= 1000000
        minor = ver / 1000
        ver %= 1000
        release = ver
        return "%s.%s.%s" % (major,minor,release)

    def is_kvm_supported(self):
        """Return KVM capabilities."""
        return util.is_kvm_available(self.get_cap_xml())

    def get_storages(self, only_actives=False):
        storages = []
        for pool in self.wvm.listStoragePools():
            storages.append(pool)
        if not only_actives:
            for pool in self.wvm.listDefinedStoragePools():
                storages.append(pool)
        return storages

    def get_networks(self):
        virtnet = []
        for net in self.wvm.listNetworks():
            virtnet.append(net)
        for net in self.wvm.listDefinedNetworks():
            virtnet.append(net)
        return virtnet

    def get_ifaces(self):
        interface = []
        for inface in self.wvm.listInterfaces():
            interface.append(inface)
        for inface in self.wvm.listDefinedInterfaces():
            interface.append(inface)
        return interface

    def get_nwfilters(self):
        nwfilters = []
        for nwfilter in self.wvm.listNWFilters():
            nwfilters.append(nwfilter)
        return nwfilters

    def get_cache_modes(self):
        """Get cache available modes"""
        return {
            'default': 'Default',
            'none': 'Disabled',
            'writethrough': 'Write through',
            'writeback': 'Write back',
            'directsync': 'Direct sync',  # since libvirt 0.9.5
            'unsafe': 'Unsafe',  # since libvirt 0.9.7
        }

    def hypervisor_type(self):
        """Return hypervisor type"""
        def hypervisors(ctx):
            result = {}
            for arch in ctx.xpath('/capabilities/guest/arch'):
                domain_types = arch.xpath('domain/@type')
                arch_name = arch.xpath('@name')[0]
                result[arch_name]= domain_types
            return result
        return util.get_xml_path(self.get_cap_xml(), func=hypervisors)

    def get_emulator(self, arch):
        """Return emulator """
        return util.get_xml_path(self.get_cap_xml(), "/capabilities/guest/arch[@name='{}']/emulator".format(arch))

    def get_emulators(self):
        def emulators(ctx):
            result = {}
            for arch in ctx.xpath('/capabilities/guest/arch'):
                emulator = arch.xpath('emulator')
                arch_name = arch.xpath('@name')[0]
                result[arch_name]= emulator
            return result
        return util.get_xml_path(self.get_cap_xml(), func=emulators)

    def get_machines(self, arch):
        """ Return machine type of emulation"""
        return util.get_xml_path(self.get_cap_xml(), "/capabilities/guest/arch[@name='{}']/machine".format(arch))

    def get_disk_bus_types(self):
        """Get available disk bus types list"""

        def get_bus_list(ctx):
            result = []
            for disk_enum in ctx.xpath('/domainCapabilities/devices/disk/enum'):
               if disk_enum.xpath("@name")[0] == "bus":
                   for values in disk_enum: result.append(values.text)
            return result

        # return [ 'ide', 'scsi', 'usb', 'virtio' ]
        return util.get_xml_path(self.get_dom_cap_xml(), func=get_bus_list)

    def get_disk_device_types(self):
        """Get available disk device type list"""

        def get_device_list(ctx):
            result = []
            for disk_enum in ctx.xpath('/domainCapabilities/devices/disk/enum'):
                if disk_enum.xpath("@name")[0] == "diskDevice":
                    for values in disk_enum: result.append(values.text)
            return result

        # return [ 'disk', 'cdrom', 'floppy', 'lun' ]
        return util.get_xml_path(self.get_dom_cap_xml(), func=get_device_list)

    def get_image_formats(self):
        """Get available image formats"""
        return [ 'raw', 'qcow', 'qcow2' ]

    def get_file_extensions(self):
        """Get available image filename extensions"""
        return [ 'img', 'qcow', 'qcow2' ]

    def get_video(self):
        """ Get available graphics video types """
        def get_video_list(ctx):
            result = []
            for video_enum in ctx.xpath('/domainCapabilities/devices/video/enum'):
                if video_enum.xpath("@name")[0] == "modelType":
                    for values in video_enum: result.append(values.text)
            return result
        return util.get_xml_path(self.get_dom_cap_xml(),func=get_video_list)

    def get_iface(self, name):
        return self.wvm.interfaceLookupByName(name)

    def get_secrets(self):
        return self.wvm.listSecrets()

    def get_secret(self, uuid):
        return self.wvm.secretLookupByUUIDString(uuid)

    def get_storage(self, name):
        return self.wvm.storagePoolLookupByName(name)

    def get_volume_by_path(self, path):
        return self.wvm.storageVolLookupByPath(path)

    def get_network(self, net):
        return self.wvm.networkLookupByName(net)

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

    def get_net_device(self):
        netdevice = []

        def get_info(doc):
            dev_type = util.get_xpath(doc, '/device/capability/@type')
            interface = util.get_xpath(doc, '/device/capability/interface')
            return dev_type, interface

        for dev in self.wvm.listAllDevices(0):
            xml = dev.XMLDesc(0)
            (dev_type, interface) = util.get_xml_path(xml, func=get_info)
            if dev_type == 'net':
                netdevice.append(interface)
        return netdevice

    def get_host_instances(self, raw_mem_size=False):
        vname = {}
        def get_info(doc):
            mem = util.get_xpath(doc, "/domain/currentMemory")
            mem = int(mem) / 1024
            if raw_mem_size:
                mem = int(mem) * (1024*1024)
            cur_vcpu = util.get_xpath(doc, "/domain/vcpu/@current")
            if cur_vcpu:
                vcpu = cur_vcpu
            else:
                vcpu = util.get_xpath(doc, "/domain/vcpu")
            title = util.get_xpath(doc, "/domain/title")
            title = title if title else ''
            description = util.get_xpath(doc, "/domain/description")
            description = description if description else ''
            return (mem, vcpu, title, description)
        for name in self.get_instances():
            dom = self.get_instance(name)
            xml = dom.XMLDesc(0)
            (mem, vcpu, title, description) = util.get_xml_path(xml, func=get_info)
            vname[dom.name()] = {
                'status': dom.info()[0],
                'uuid': dom.UUIDString(),
                'vcpu': vcpu,
                'memory': mem,
                'title': title,
                'description': description,
            }
        return vname

    def get_user_instances(self, name):
        dom = self.get_instance(name)
        xml = dom.XMLDesc(0)
        def get_info(ctx):
            mem = util.get_xpath(ctx, "/domain/currentMemory")
            mem = int(mem) / 1024
            cur_vcpu = util.get_xpath(ctx, "/domain/vcpu/@current")
            if cur_vcpu:
                vcpu = cur_vcpu
            else:
                vcpu = util.get_xpath(ctx, "/domain/vcpu")
            title = util.get_xpath(ctx, "/domain/title")
            title = title if title else ''
            description = util.get_xpath(ctx, "/domain/description")
            description = description if description else ''
            return (mem, vcpu, title, description)
        (mem, vcpu, title, description) = util.get_xml_path(xml, func=get_info)
        return {
            'name': dom.name(),
            'status': dom.info()[0],
            'uuid': dom.UUIDString(),
            'vcpu': vcpu,
            'memory': mem,
            'title': title,
            'description': description,
        }

    def close(self):
        """Close connection"""
        # to-do: do not close connection ;)
        # self.wvm.close()
        pass
