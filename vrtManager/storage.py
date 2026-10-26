import contextlib

import libvirt
from vrtManager import util
from vrtManager.connection import wvmConnect


class wvmStorages(wvmConnect):
    def get_storages_info(self):
        get_storages = self.get_storages()
        storages = []
        for pool in get_storages:
            stg = self.get_storage(pool)
            stg_status = stg.isActive()
            stg_type = util.get_xml_path(stg.XMLDesc(0), "/pool/@type")
            stg_vol = len(stg.listVolumes()) if stg_status else None
            _state, stg_size, _allocation, stg_free = stg.info()
            storages.append(
                {
                    "name": pool,
                    "status": stg_status,
                    "type": stg_type,
                    "volumes": stg_vol,
                    "size": stg_size,
                    "free": stg_free,
                }
            )
        return storages

    def define_storage(self, xml, flags):
        """Define the pool, start it with flags and set it to autostart. A
        pool that does not start is undefined again, so its name stays free
        for another try."""
        stg = self.wvm.storagePoolDefineXML(xml, 0)
        try:
            stg.create(flags)
        except libvirt.libvirtError:
            stg.undefine()
            raise
        stg.setAutostart(1)
        return stg

    def get_pool_by_target(self, target):
        pool_names = self.get_storages()
        for pool_name in pool_names:
            stg = wvmStorage(self.host, self.login, self.passwd, self.conn, pool_name)
            if stg.get_target_path() == target:
                return self.get_storage(pool_name)
            if stg.get_type() == "rbd" and stg.get_source_name() == target:
                return self.get_storage(pool_name)
        return None

    def create_storage(self, stg_type, name, source, target):
        xml = f"""<pool type='{stg_type}'>
                 <name>{name}</name>"""
        if stg_type == "logical":
            xml += f"""<source>
                            <device path='{source}'/>
                            <name>{name}</name>
                            <format type='lvm2'/>
                        </source>"""
        if stg_type == "logical":
            target = f"/dev/{name}"
        xml += f"""
                  <target>
                       <path>{target}</path>
                  </target>
                </pool>"""
        # builds the dir pool's directory or the logical pool's volume group
        return self.define_storage(xml, libvirt.VIR_STORAGE_POOL_CREATE_WITH_BUILD)

    def create_storage_ceph(
        self, stg_type, name, ceph_pool, ceph_host, ceph_user, secret
    ):
        ceph_pool, ceph_host, ceph_user, secret = map(util.xml_escape, (ceph_pool, ceph_host, ceph_user, secret))
        xml = f"""
                <pool type='{stg_type}'>
                <name>{name}</name>
                <source>
                    <name>{ceph_pool}</name>
                    <host name='{ceph_host}' port='6789'/>
                    <auth username='{ceph_user}' type='ceph'>
                        <secret uuid='{secret}'/>
                    </auth>
                </source>
                </pool>
                """
        self.define_storage(xml, 0)

    def create_storage_netfs(
        self, stg_type, name, netfs_host, source, source_format, target
    ):
        netfs_host, source_format = util.xml_escape(netfs_host), util.xml_escape(source_format)
        xml = f"""
                <pool type='{stg_type}'>
                <name>{name}</name>
                <source>
                    <host name='{netfs_host}'/>
                    <dir path='{source}'/>
                    <format type='{source_format}'/>
                </source>
                <target>
                    <path>{target}</path>
                </target>
                </pool>
                """
        # builds the mount point
        return self.define_storage(xml, libvirt.VIR_STORAGE_POOL_CREATE_WITH_BUILD)


class wvmStorage(wvmConnect):
    def __init__(self, host, login, passwd, conn, pool):
        wvmConnect.__init__(self, host, login, passwd, conn)
        self.pool = self.get_storage(pool)

    def get_name(self):
        return self.pool.name()

    def get_status(self):
        status = [
            "Not running",
            "Initializing pool, not available",
            "Running normally",
            "Running degraded",
        ]
        try:
            return status[self.pool.info()[0]]
        except ValueError:
            return "Unknown"

    def get_size(self):
        return [self.pool.info()[1], self.pool.info()[3]]

    def _XMLDesc(self, flags):
        return self.pool.XMLDesc(flags)

    def _createXML(self, xml, flags):
        self.pool.createXML(xml, flags)

    def _createXMLFrom(self, xml, vol, flags):
        self.pool.createXMLFrom(xml, vol, flags)

    def _define(self, xml):
        return self.wvm.storagePoolDefineXML(xml, 0)

    def is_active(self):
        return self.pool.isActive()

    def get_uuid(self):
        return self.pool.UUIDString()

    def start(self):
        return self.pool.create(0)

    def stop(self):
        """Refused while it holds a disk of a running VM, named by the pool
        or by a volume's path: that VM would lose the disk."""
        name = self.pool.name()
        paths = {vol.path() for vol in self.pool.listAllVolumes()}
        vms = self.domains_using(
            lambda domain: domain.xpath("devices/disk/source[@pool=$name]", name=name)
            or paths.intersection(self._source_paths(domain)),
            running_only=True,
        )
        if vms:
            raise util.OperationError(f"Pool {name} holds disks of the running VMs {', '.join(vms)}; "
                                      "shut them down first")
        return self.pool.destroy()

    def delete(self):
        """Refused while a VM's definition names it for a disk: that VM would
        no longer start. A disk given by its file path does not need it."""
        name = self.pool.name()
        if vms := self.domains_using(lambda domain: domain.xpath("devices/disk/source[@pool=$name]", name=name)):
            raise util.OperationError(f"VMs {', '.join(vms)} have disks in pool {name} by its name and would no "
                                      "longer start; detach those disks first")
        self.pool.undefine()

    def get_autostart(self):
        return self.pool.autostart()

    def set_autostart(self, value):
        self.pool.setAutostart(value)

    def get_type(self):
        return util.get_xml_path(self._XMLDesc(0), "/pool/@type")

    def get_target_path(self):
        return util.get_xml_path(self._XMLDesc(0), "/pool/target/path")

    def get_source_name(self):
        return util.get_xml_path(self._XMLDesc(0), "/pool/source/name")

    def get_allocation(self):
        return int(util.get_xml_path(self._XMLDesc(0), "/pool/allocation"))

    def get_available(self):
        return int(util.get_xml_path(self._XMLDesc(0), "/pool/available"))

    def get_capacity(self):
        return int(util.get_xml_path(self._XMLDesc(0), "/pool/capacity"))

    def get_rbd_source(self):
        def hosts(doc):
            hosts_array = []

            for host in doc.xpath("/pool/source/host"):
                name = host.get("name")
                if name:
                    port = host.get("port")
                    if port:
                        hosts_array.append({"hostname": name, "hostport": port})
                    else:
                        hosts_array.append({"hostname": name})

            name = doc.get("name")
            auth = doc.xpath("/pool/source/auth")
            auth_type = auth[0].get("type")
            auth_user = auth[0].get("username")
            auth_uuid = auth[0].xpath("secret/@uuid")[0]

            return {
                "name": name,
                "auth_type": auth_type,
                "auth_user": auth_user,
                "auth_uuid": auth_uuid,
                "hosts": hosts_array,
            }

        return util.get_xml_path(self._XMLDesc(0), func=hosts)

    def get_pretty_allocation(self):
        return util.pretty_bytes(self.get_allocation())

    def get_pretty_available(self):
        return util.pretty_bytes(self.get_available())

    def get_pretty_capacity(self):
        return util.pretty_bytes(self.get_capacity())

    def get_volumes(self):
        return self.pool.listVolumes()

    def get_volume(self, name):
        return self.pool.storageVolLookupByName(name)

    def get_volume_size(self, name):
        vol = self.get_volume(name)
        return vol.info()[1]

    def get_volume_allocation(self, name):
        vol = self.get_volume(name)
        return vol.info()[2]

    def _vol_XMLDesc(self, name):
        vol = self.get_volume(name)
        return vol.XMLDesc(0)

    def del_volume(self, name):
        """libvirt deletes any volume; one a VM still needs is refused."""
        vol = self.pool.storageVolLookupByName(name)
        if vol.path() in self.paths_in_use():
            raise util.OperationError(f"Volume {name} is in use: a VM's disk, a backing file or a snapshot's file")
        vol.delete(0)

    def get_volume_format_type(self, name):
        vol_xml = self._vol_XMLDesc(name)
        return util.get_xml_path(vol_xml, "/volume/target/format/@type")

    def get_volume_type(self, name):
        vol_xml = self._vol_XMLDesc(name)
        return util.get_xml_path(vol_xml, "/volume/@type")

    def refresh(self):
        return self.pool.refresh(0)

    def get_volumes_details(self):
        with contextlib.suppress(Exception):
            self.refresh()

        vols = self.get_volumes()
        return [
            {
                "name": volname,
                "size": self.get_volume_size(volname),
                "allocation": self.get_volume_allocation(volname),
                "type": self.get_volume_format_type(volname),
            }
            for volname in vols
        ]

    def get_volume_details(self, volname):
        with contextlib.suppress(Exception):
            self.refresh()
        return {
            "name": volname,
            "size": self.get_volume_size(volname),
            "allocation": self.get_volume_allocation(volname),
            "type": self.get_volume_format_type(volname),
        }

    def update_volumes(self):
        with contextlib.suppress(Exception):
            self.refresh()
        vols = self.get_volumes()
        return [
            {
                "name": volname,
                "size": self.get_volume_size(volname),
                "allocation": self.get_volume_allocation(volname),
                "type": self.get_volume_format_type(volname),
            }
            for volname in vols
        ]

    def create_volume(
        self,
        name,
        size,
        vol_fmt="qcow2",
        metadata=False,
        disk_owner_uid=0,
        disk_owner_gid=0,
    ):
        size = int(size) * 1073741824
        storage_type = self.get_type()
        alloc = size
        if vol_fmt == "unknown":
            vol_fmt = "raw"
        if storage_type == "dir":
            name += f".{vol_fmt}" if vol_fmt in ("qcow", "qcow2") else ".img"
            alloc = 0
        xml = f"""
            <volume>
                <name>{util.xml_escape(name)}</name>
                <capacity>{size}</capacity>
                <allocation>{alloc}</allocation>
                <target>
                    <format type='{vol_fmt}'/>
                     <permissions>
                        <owner>{disk_owner_uid}</owner>
                        <group>{disk_owner_gid}</group>
                        <mode>0644</mode>
                        <label>virt_image_t</label>
                    </permissions>"""
        if vol_fmt == "qcow2":
            xml += """
                      <compat>1.1</compat>
                      <features>
                         <lazy_refcounts/>
                      </features>"""
        xml += """</target>
                </volume>"""
        self._createXML(xml, metadata)
        return name

    def clone_name(self, target_file, vol_fmt, file_suffix="img"):
        """The name clone_volume gives a copy: a dir pool adds the format's suffix."""
        if self.get_type() != "dir":
            return target_file
        if vol_fmt in ("qcow", "qcow2"):
            return f"{target_file}.{vol_fmt}"
        return f"{target_file}.{file_suffix}" if file_suffix else target_file

    def clone_volume(
        self,
        name,
        target_file,
        vol_fmt=None,
        metadata=False,
        mode="0644",
        file_suffix="img",
        disk_owner_uid=0,
        disk_owner_gid=0,
    ):
        vol = self.get_volume(name)
        if not vol_fmt:
            vol_fmt = self.get_volume_format_type(name)

        target_file = self.clone_name(target_file, vol_fmt, file_suffix)

        xml = f"""
            <volume>
                <name>{target_file}</name>
                <capacity>0</capacity>
                <allocation>0</allocation>
                <target>
                    <format type='{vol_fmt}'/>
                    <permissions>
                        <owner>{disk_owner_uid}</owner>
                        <group>{disk_owner_gid}</group>
                        <mode>{mode}</mode>
                        <label>virt_image_t</label>
                    </permissions>"""
        if vol_fmt == "qcow2":
            xml += """
                    <compat>1.1</compat>
                    <features>
                        <lazy_refcounts/>
                    </features>"""
        xml += """ </target>
            </volume>"""
        self._createXMLFrom(xml, vol, metadata)
        return target_file
