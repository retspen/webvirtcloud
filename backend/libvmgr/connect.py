import libvirt
import threading
import socket
from libvmgr import util
from libvmgr.rwlock import ReadWriteLock
from libvirt import libvirtError


CONN_SOCKET = 4
CONN_TLS = 3
CONN_SSH = 2
CONN_TCP = 1
TLS_PORT = 16514
SSH_PORT = 22
TCP_PORT = 16509
KEEPALIVE_COUNT = 30
KEEPALIVE_INTERVAL = 5


def host_is_up(conn_type, hostname):
    """
    returns True if the given host is up and we are able to establish
    a connection using the given credentials.
    """
    try:
        socket_host = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_host.settimeout(2)
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
    except socket.error:
        raise libvirtError('Unable to connect to host server: Operation timed out')


class wvcEventLoop(threading.Thread):
    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}):
        # register the default event implementation
        # of libvirt, as we do not have an existing
        # event loop.
        libvirt.virEventRegisterDefaultImpl()

        if name is None:
            name = 'libvirt event loop'

        super(wvcEventLoop, self).__init__(group, target, name, args, kwargs)

        # we run this thread in deamon mode, so it does
        # not block shutdown of the server
        self.daemon = True

    def run(self):
        while True:
            # if this method will fail it raises libvirtError
            # we do not catch the exception here so it will show up
            # in the logs. Not sure when this call will ever fail
            libvirt.virEventRunDefaultImpl()


class wvcConnection(object):
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
                        self.connection.setKeepAlive(connection_manager.keepalive_interval,
                                                     connection_manager.keepalive_count)
                        try:
                            self.connection.registerCloseCallback(self.__connection_close_callback, None)
                        except Exception:
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
                self.last_error = 'Connection closed'

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
            except Exception:
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
        return '<wvcConnection {connection_str}>'.format(connection_str=str(self))


class wvcConnectionManager(object):
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
        self._event_loop = wvcEventLoop()
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
        # force all string values to unicode changed for Python3 to str
        host = str(host)
        login = str(login)
        passwd = str(passwd) if passwd is not None else None

        connection = self._search_connection(host, login, passwd, conn)

        if (connection is None):
            self._connections_lock.acquireWrite()
            try:
                # we have to search for the connection again after aquireing the write lock
                # as the thread previously holding the write lock may have already added our connection
                connection = self._search_connection(host, login, passwd, conn)
                if (connection is None):
                    # create a new connection if a matching connection does not already exist
                    connection = wvcConnection(host, login, passwd, conn)

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


connection_manager = wvcConnectionManager(KEEPALIVE_INTERVAL, KEEPALIVE_COUNT)


class wvcConnect(object):
    def __init__(self, host, login=None, passwd=None, conn_type=CONN_SOCKET, keepalive=True):
        self.login = login
        self.host = host
        self.passwd = passwd
        self.conn_type = conn_type
        self.keepalive = keepalive

        # is host up?
        host_is_up(self.conn_type, self.host)

        # get connection from connection manager
        if self.keepalive:
            self.conn = connection_manager.get_connection(host, login, passwd, conn_type)
        else:
            if self.conn_type == CONN_TCP:
                def creds(credentials, user_data):
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

                flags = [libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE]
                auth = [flags, creds, None]
                uri = 'qemu+tcp://%s/system' % self.host
                try:
                    self.conn = libvirt.openAuth(uri, auth, 0)
                except libvirtError:
                    raise libvirtError('Connection Failed')

            if self.conn_type == CONN_SSH:
                uri = 'qemu+ssh://%s@%s/system' % (self.login, self.host)
                try:
                    self.conn = libvirt.open(uri)
                except libvirtError as err:
                    raise err

            if self.conn_type == CONN_TLS:
                def creds(credentials, user_data):
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

                flags = [libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE]
                auth = [flags, creds, None]
                uri = 'qemu+tls://%s@%s/system' % (self.login, self.host)
                try:
                    self.conn = libvirt.openAuth(uri, auth, 0)
                except libvirtError:
                    raise libvirtError('Connection Failed')

    def get_cap_xml(self):
        """Return xml capabilities"""
        return self.conn.getCapabilities()

    def is_kvm_supported(self):
        """Return KVM capabilities."""
        return util.is_kvm_available(self.get_cap_xml())

    def get_storages(self):
        storages = []
        for pool in self.conn.listStoragePools():
            storages.append(pool)
        for pool in self.conn.listDefinedStoragePools():
            storages.append(pool)
        return storages

    def get_networks(self):
        virtnet = []
        for net in self.conn.listNetworks():
            virtnet.append(net)
        for net in self.conn.listDefinedNetworks():
            virtnet.append(net)
        return virtnet

    def get_ifaces(self):
        interface = []
        for inface in self.conn.listInterfaces():
            interface.append(inface)
        for inface in self.conn.listDefinedInterfaces():
            interface.append(inface)
        return interface

    def get_iface(self, name):
        return self.conn.interfaceLookupByName(name)

    def get_secrets(self):
        return self.conn.listSecrets()

    def get_secret(self, uuid):
        return self.conn.secretLookupByUUIDString(uuid)

    def get_storage(self, name):
        return self.conn.storagePoolLookupByName(name)

    def get_volume_by_path(self, path):
        return self.conn.storageVolLookupByPath(path)

    def get_network(self, net):
        return self.conn.networkLookupByName(net)

    def get_instance(self, name):
        return self.conn.lookupByName(name)

    def get_instance_status(self, name):
        dom = self.conn.lookupByName(name)
        return dom.info()[0]

    def get_instances(self):
        instances = []
        for inst_id in self.conn.listDomainsID():
            dom = self.conn.lookupByID(int(inst_id))
            instances.append(dom.name())
        for name in self.conn.listDefinedDomains():
            instances.append(name)
        return instances

    def get_snapshots(self):
        instance = []
        for snap_id in self.conn.listDomainsID():
            dom = self.conn.lookupByID(int(snap_id))
            if dom.snapshotNum(0) != 0:
                instance.append(dom.name())
        for name in self.conn.listDefinedDomains():
            dom = self.conn.lookupByName(name)
            if dom.snapshotNum(0) != 0:
                instance.append(dom.name())
        return instance

    def get_net_device(self):
        netdevice = []
        for dev in self.conn.listAllDevices(0):
            xml = dev.XMLDesc(0)
            if util.get_xml_data(xml, 'capability', 'type') == 'net':
                netdevice.append(util.get_xml_data(xml, 'capability/interface'))
        return netdevice

    def get_host_instances(self):
        vname = {}
        for name in self.get_instances():
            dom = self.get_instance(name)
            mem = util.get_xml_data(dom.XMLDesc(0), 'currentMemory')
            mem = round(int(mem) / 1024)
            cur_vcpu = util.get_xml_data(dom.XMLDesc(0), 'vcpu', 'current')
            if cur_vcpu:
                vcpu = cur_vcpu
            else:
                vcpu = util.get_xml_data(dom.XMLDesc(0), 'vcpu')
            vname[dom.name()] = {'status': dom.info()[0], 'uuid': dom.UUIDString(), 'vcpu': vcpu, 'memory': mem}
        return vname

    def close(self):
        """Close connection"""
        if not self.keepalive:
            self.conn.close()
