import string
from vrtManager import util
from vrtManager.connection import wvmConnect


def get_rbd_storage_data(stg):
    xml = stg.XMLDesc(0)
    ceph_user = util.get_xml_path(xml, "/pool/source/auth/@username")

    def get_ceph_hosts(doc):
        hosts = list()
        for host in doc.xpath("/pool/source/host"):
            name = host.prop("name")
            if name:
                hosts.append({'name': name, 'port': host.prop("port")})
        return hosts
    ceph_hosts = util.get_xml_path(xml, func=get_ceph_hosts)
    secret_uuid = util.get_xml_path(xml, "/pool/source/auth/secret/@uuid")
    return ceph_user, secret_uuid, ceph_hosts


class wvmCreate(wvmConnect):

    def get_storages_images(self):
        """
        Function return all images on all storages
        """
        images = list()
        storages = self.get_storages(only_actives=True)
        for storage in storages:
            stg = self.get_storage(storage)
            try:
                stg.refresh(0)
            except:
                pass
            for img in stg.listVolumes():
                if img.lower().endswith('.iso'):
                    pass
                else:
                    images.append(img)
        return images

    def get_os_type(self):
        """Get guest os type"""
        return util.get_xml_path(self.get_cap_xml(), "/capabilities/guest/os_type")

    def get_host_arch(self):
        """Get guest capabilities"""
        return util.get_xml_path(self.get_cap_xml(), "/capabilities/host/cpu/arch")

    def create_volume(self, storage, name, size, image_format, metadata=False, disk_owner_uid=0, disk_owner_gid=0):
        size = int(size) * 1073741824
        stg = self.get_storage(storage)
        storage_type = util.get_xml_path(stg.XMLDesc(0), "/pool/@type")
        if storage_type == 'dir':
            if image_format in ('qcow', 'qcow2'):
                name += '.' + image_format
            else:
                name += '.img'
            alloc = 0
        else:
            alloc = size
            metadata = False
        xml = f"""
            <volume>
                <name>{name}</name>
                <capacity>{size}</capacity>
                <allocation>{alloc}</allocation>
                <target>
                    <format type='{image_format}'/>
                     <permissions>
                        <owner>{disk_owner_uid}</owner>
                        <group>{disk_owner_gid}</group>
                        <mode>0644</mode>
                        <label>virt_image_t</label>
                    </permissions>
                    <compat>1.1</compat>
                    <features>
                        <lazy_refcounts/>
                    </features>
                </target>
            </volume>"""
        stg.createXML(xml, metadata)
        try:
            stg.refresh(0)
        except:
            pass
        vol = stg.storageVolLookupByName(name)
        return vol.path()

    def get_volume_type(self, path):
        vol = self.get_volume_by_path(path)
        vol_type = util.get_xml_path(vol.XMLDesc(0), "/volume/target/format/@type")
        if vol_type == 'unknown' or vol_type == 'iso':
            return 'raw'
        if vol_type:
            return vol_type
        else:
            return 'raw'

    def get_volume_path(self, volume, pool=None):
        if not pool:
            storages = self.get_storages(only_actives=True)
        else:
            storages = [pool]
        for storage in storages:
            stg = self.get_storage(storage)
            if stg.info()[0] != 0:
                stg.refresh(0)
                for img in stg.listVolumes():
                    if img == volume:
                        vol = stg.storageVolLookupByName(img)
                        return vol.path()

    def get_storage_by_vol_path(self, vol_path):
        vol = self.get_volume_by_path(vol_path)
        return vol.storagePoolLookupByVolume()

    def clone_from_template(self, clone, template, storage=None, metadata=False, disk_owner_uid=0, disk_owner_gid=0):
        vol = self.get_volume_by_path(template)
        if not storage:
            stg = vol.storagePoolLookupByVolume()
        else:
            stg = self.get_storage(storage)

        storage_type = util.get_xml_path(stg.XMLDesc(0), "/pool/@type")
        format = util.get_xml_path(vol.XMLDesc(0), "/volume/target/format/@type")
        if storage_type == 'dir':
            clone += '.img'
        else:
            metadata = False
        xml = f"""
            <volume>
                <name>{clone}</name>
                <capacity>0</capacity>
                <allocation>0</allocation>
                <target>
                    <format type='{format}'/>
                     <permissions>
                        <owner>{disk_owner_uid}</owner>
                        <group>{disk_owner_gid}</group>
                        <mode>0644</mode>
                        <label>virt_image_t</label>
                    </permissions>
                    <compat>1.1</compat>
                    <features>
                        <lazy_refcounts/>
                    </features>
                </target>
            </volume>"""
        stg.createXMLFrom(xml, vol, metadata)
        clone_vol = stg.storageVolLookupByName(clone)
        return clone_vol.path()

    def _defineXML(self, xml):
        self.wvm.defineXML(xml)

    def delete_volume(self, path):
        vol = self.get_volume_by_path(path)
        vol.delete()

    def create_instance(self, name, memory, vcpu, vcpu_mode, uuid, arch, machine, firmware, volumes,
                        networks, nwfilter, graphics, virtio, listen_addr,
                        video="vga", console_pass="random", mac=None, qemu_ga=True):
        """
        Create VM function
        """
        caps = self.get_capabilities(arch)
        dom_caps = self.get_dom_capabilities(arch, machine)

        memory = int(memory) * 1024

        xml = f"""
                <domain type='{dom_caps["domain"]}'>
                  <name>{name}</name>
                  <description>None</description>
                  <uuid>{uuid}</uuid>
                  <memory unit='KiB'>{memory}</memory>
                  <vcpu>{vcpu}</vcpu>"""

        if dom_caps["os_support"] == 'yes':
            xml += f"""<os>
                          <type arch='{arch}' machine='{machine}'>{caps["os_type"]}</type>"""
            xml += """    <boot dev='hd'/>
                          <boot dev='cdrom'/>
                          <bootmenu enable='yes'/>"""
            if firmware:
                if firmware["secure"] == 'yes':
                    xml += """<loader readonly='%s' type='%s' secure='%s'>%s</loader>""" % (firmware["readonly"],
                                                                                            firmware["type"],
                                                                                            firmware["secure"],
                                                                                            firmware["loader"])
                if firmware["secure"] == 'no':
                    xml += """<loader readonly='%s' type='%s'>%s</loader>""" % (firmware["readonly"],
                                                                                firmware["type"],
                                                                                firmware["loader"])
            xml += """</os>"""

        if caps["features"]:
            xml += """<features>"""
            if 'acpi' in caps["features"]:
                xml += """<acpi/>"""
            if 'apic' in caps["features"]:
                xml += """<apic/>"""
            if 'pae' in caps["features"]:
                xml += """<pae/>"""
            if  firmware.get("secure", 'no') == 'yes':
                xml += """<smm state="on"/>"""
            xml += """</features>"""

        if vcpu_mode == "host-model":
            xml += """<cpu mode='host-model'/>"""
        elif vcpu_mode == "host-passthrough":
            xml += """<cpu mode='host-passthrough'/>"""
        elif vcpu_mode == "":
            pass
        else:
            xml += f"""<cpu mode='custom' match='exact' check='none'>
                        <model fallback='allow'>{vcpu_mode}</model>"""
            xml += """</cpu>"""

        xml += """
                  <clock offset="utc"/>
                  <on_poweroff>destroy</on_poweroff>
                  <on_reboot>restart</on_reboot>
                  <on_crash>restart</on_crash>
                """
        xml += """<devices>"""

        vd_disk_letters = list(string.ascii_lowercase)
        fd_disk_letters = list(string.ascii_lowercase)
        hd_disk_letters = list(string.ascii_lowercase)
        sd_disk_letters = list(string.ascii_lowercase)
        add_cd = True

        for volume in volumes:

            disk_opts = ''
            if volume['cache_mode'] is not None and volume['cache_mode'] != 'default':
                disk_opts += f"cache='{volume['cache_mode']}' "
            if volume['io_mode'] is not None and volume['io_mode'] != 'default':
                disk_opts += f"io='{volume['io_mode']}' "
            if volume['discard_mode'] is not None and volume['discard_mode'] != 'default':
                disk_opts += f"discard='{volume['discard_mode']}' "
            if volume['detect_zeroes_mode'] is not None and volume['detect_zeroes_mode'] != 'default':
                disk_opts += f"detect_zeroes='{volume['detect_zeroes_mode']}' "

            stg = self.get_storage_by_vol_path(volume['path'])
            stg_type = util.get_xml_path(stg.XMLDesc(0), "/pool/@type")

            if volume['device'] == 'cdrom': add_cd = False

            if stg_type == 'rbd':
                ceph_user, secret_uuid, ceph_hosts = get_rbd_storage_data(stg)
                xml += """<disk type='network' device='disk'>
                            <driver name='qemu' type='%s' %s />""" % (volume['type'], disk_opts)
                xml += """  <auth username='%s'>
                                <secret type='ceph' uuid='%s'/>
                            </auth>
                            <source protocol='rbd' name='%s'>""" % (ceph_user, secret_uuid, volume['path'])
                if isinstance(ceph_hosts, list):
                    for host in ceph_hosts:
                        if host.get('port'):
                            xml += """
                                   <host name='%s' port='%s'/>""" % (host.get('name'), host.get('port'))
                        else:
                            xml += """
                                   <host name='%s'/>""" % host.get('name')
                xml += """</source>"""
            else:
                xml += """<disk type='file' device='%s'>""" % volume['device']
                xml += """ <driver name='qemu' type='%s' %s/>""" % (volume['type'], disk_opts)
                xml += f""" <source file='%s'/>""" % volume['path']

            if volume.get('bus') == 'virtio':
                xml += """<target dev='vd%s' bus='%s'/>""" % (vd_disk_letters.pop(0), volume.get('bus'))
            elif volume.get('bus') == 'ide':
                xml += """<target dev='hd%s' bus='%s'/>""" % (hd_disk_letters.pop(0), volume.get('bus'))
            elif volume.get('bus') == 'fdc':
                xml += """<target dev='fd%s' bus='%s'/>""" % (fd_disk_letters.pop(0), volume.get('bus'))
            elif volume.get('bus') == 'sata' or volume.get('bus') == 'scsi':
                xml += """<target dev='sd%s' bus='%s'/>""" % (sd_disk_letters.pop(0), volume.get('bus'))
            else:
                xml += """<target dev='sd%s'/>""" % sd_disk_letters.pop(0)
            xml += """</disk>"""

            if volume.get('bus') == 'scsi':
                xml += f"""<controller type='scsi' model='{volume.get('scsi_model')}'/>"""

        if add_cd:
            xml += """<disk type='file' device='cdrom'>
                          <driver name='qemu' type='raw'/>
                          <source file = '' />
                          <readonly/>"""
            if 'ide' in dom_caps['disk_bus']:
                xml += """<target dev='hd%s' bus='%s'/>""" % (hd_disk_letters.pop(0), 'ide')
            elif 'sata' in dom_caps['disk_bus']:
                xml += """<target dev='sd%s' bus='%s'/>""" % (sd_disk_letters.pop(0), 'sata')
            elif 'scsi' in dom_caps['disk_bus']:
                xml += """<target dev='sd%s' bus='%s'/>""" % (sd_disk_letters.pop(0), 'scsi')
            else:
                xml += """<target dev='vd%s' bus='%s'/>""" % (vd_disk_letters.pop(0), 'virtio')
            xml += """</disk>"""

        for net in networks.split(','):
            xml += """<interface type='network'>"""
            if mac:
                xml += f"""<mac address='{mac}'/>"""
            xml += f"""<source network='{net}'/>"""
            if nwfilter:
                xml += f"""<filterref filter='{nwfilter}'/>"""
            if virtio:
                xml += """<model type='virtio'/>"""
            xml += """</interface>"""

        if console_pass == "random":
            console_pass = "passwd='" + util.randomPasswd() + "'"
        else:
            if not console_pass == "":
                console_pass = "passwd='" + console_pass + "'"

        if 'usb' in dom_caps['disk_bus']:
            xml += """<input type='mouse' bus='{}'/>""".format('virtio' if virtio else 'usb')
            xml += """<input type='keyboard' bus='{}'/>""".format('virtio' if virtio else 'usb')
            xml += """<input type='tablet' bus='{}'/>""".format('virtio' if virtio else 'usb')
        else:
            xml += """<input type='mouse'/>"""
            xml += """<input type='keyboard'/>"""
            xml += """<input type='tablet'/>"""

        xml += f"""
                <graphics type='{graphics}' port='-1' autoport='yes' {console_pass} listen='{listen_addr}'/>
                <console type='pty'/> """

        if qemu_ga and virtio:
            xml += """ <channel type='unix'>
                            <target type='virtio' name='org.qemu.guest_agent.0'/>
                       </channel>"""

        xml += f""" <video>
                      <model type='{video}'/>
                   </video>
              </devices>
            </domain>"""
        self._defineXML(xml)
