import string
from vrtManager import util
from vrtManager.connection import wvmConnect
from webvirtcloud.settings import INSTANCE_VOLUME_DEFAULT_OWNER as DEFAULT_OWNER
from webvirtcloud.settings import INSTANCE_VOLUME_DEFAULT_FORMAT
from webvirtcloud.settings import INSTANCE_VOLUME_DEFAULT_SCSI_CONTROLLER
from webvirtcloud.settings import INSTANCE_VOLUME_DEFAULT_DRIVER_OPTS as OPTS



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
    image_format = INSTANCE_VOLUME_DEFAULT_FORMAT

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

    def create_volume(self, storage, name, size, image_format=image_format, metadata=False, owner=DEFAULT_OWNER):
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
        xml = """
            <volume>
                <name>%s</name>
                <capacity>%s</capacity>
                <allocation>%s</allocation>
                <target>
                    <format type='%s'/>
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
                </target>
            </volume>""" % (name, size, alloc, image_format, owner['uid'], owner['guid'])
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

    def clone_from_template(self, clone, template, storage=None, metadata=False, owner=DEFAULT_OWNER):
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
        xml = """
            <volume>
                <name>%s</name>
                <capacity>0</capacity>
                <allocation>0</allocation>
                <target>
                    <format type='%s'/>
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
                </target>
            </volume>""" % (clone, format, owner['uid'], owner['guid'])
        stg.createXMLFrom(xml, vol, metadata)
        clone_vol = stg.storageVolLookupByName(clone)
        return clone_vol.path()

    def _defineXML(self, xml):
        self.wvm.defineXML(xml)

    def delete_volume(self, path):
        vol = self.get_volume_by_path(path)
        vol.delete()

    def create_instance(self, name, memory, vcpu, vcpu_mode, uuid, arch, machine, firmware, images, cache_mode, networks, nwfilter, graphics, virtio, listen_addr, video="vga", console_pass="random", mac=None, qemu_ga=False):
        """
        Create VM function
        """
        caps = self.get_capabilities(arch)
        dom_caps = self.get_dom_capabilities(arch, machine)

        memory = int(memory) * 1024
        #hypervisor_type = 'kvm' if self.is_kvm_supported() else 'qemu'

        xml = """
                <domain type='%s'>
                  <name>%s</name>
                  <description>None</description>
                  <uuid>%s</uuid>
                  <memory unit='KiB'>%s</memory>
                  <vcpu>%s</vcpu>""" % (dom_caps["domain"], name, uuid, memory, vcpu)

        if dom_caps["os_support"] == 'yes':
            xml += """<os>
                          <type arch='%s' machine='%s'>%s</type>""" % (arch, machine, caps["os_type"])
            xml += """    <boot dev='hd'/>
                          <boot dev='cdrom'/>
                          <bootmenu enable='yes'/>"""
            if 'UEFI' in firmware:
                xml += """<loader readonly='yes' type='pflash'>%s</loader>""" % firmware.split(":")[1].strip()
            xml += """</os>"""

        if caps["features"]:
            xml += """<features>"""
            if 'acpi' in caps["features"]:
                xml += """<acpi/>"""
            if 'apic' in caps["features"]:
                xml += """<apic/>"""
            if 'pae' in caps["features"]:
                xml += """<pae/>"""
            xml += """</features>"""

        if vcpu_mode == "host-model":
            xml += """<cpu mode='host-model'/>"""
        elif vcpu_mode == "host-passthrough":
            xml += """<cpu mode='host-passthrough'/>"""
        elif vcpu_mode == "":
            pass
        else:
            xml += """<cpu mode='custom' match='exact' check='none'>
                        <model fallback='allow'>{}</model>
                      </cpu>""".format(vcpu_mode)

        xml += """
                  <clock offset="utc"/>
                  <on_poweroff>destroy</on_poweroff>
                  <on_reboot>restart</on_reboot>
                  <on_crash>restart</on_crash>
                """
        xml += """<devices>"""

        vd_disk_letters = list(string.lowercase)
        fd_disk_letters = list(string.lowercase)
        hd_disk_letters = list(string.lowercase)
        sd_disk_letters = list(string.lowercase)
        add_cd = True
        for volume in images:
            stg = self.get_storage_by_vol_path(volume['path'])
            stg_type = util.get_xml_path(stg.XMLDesc(0), "/pool/@type")

            if volume['device'] == 'cdrom': add_cd = False

            if stg_type == 'rbd':
                ceph_user, secret_uuid, ceph_hosts = get_rbd_storage_data(stg)
                xml += """<disk type='network' device='disk'>
                            <driver name='qemu' type='%s' cache='%s' %s />""" % (volume['type'], cache_mode, OPTS.get("network", ''))
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
                xml += """ <driver name='qemu' type='%s' cache='%s' %s/>""" % (volume['type'], cache_mode, OPTS.get("file", ''))
                xml += """ <source file='%s'/>""" % volume['path']

            if volume['bus'] == 'virtio':
                xml += """<target dev='vd%s' bus='%s'/>""" % (vd_disk_letters.pop(0), volume['bus'])
            elif volume['bus'] == 'ide':
                xml += """<target dev='hd%s' bus='%s'/>""" % (hd_disk_letters.pop(0), volume['bus'])
            elif volume['bus'] == 'fdc':
                xml += """<target dev='fd%s' bus='%s'/>""" % (fd_disk_letters.pop(0), volume['bus'])
            else:
                xml += """<target dev='sd%s' bus='%s'/>""" % (sd_disk_letters.pop(0), volume['bus'])
            xml += """</disk>"""
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

        if volume['bus'] == 'scsi':
            xml += """<controller type='scsi' model='%s'/>""" % INSTANCE_VOLUME_DEFAULT_SCSI_CONTROLLER

        for net in networks.split(','):
            xml += """<interface type='network'>"""
            if mac:
                xml += """<mac address='%s'/>""" % mac
            xml += """<source network='%s'/>""" % net
            if nwfilter:
                xml += """<filterref filter='%s'/>""" % nwfilter
            if virtio:
                xml += """<model type='virtio'/>"""
            xml += """</interface>"""

        if console_pass == "random":
            console_pass = "passwd='" + util.randomPasswd() + "'"
        else:
            if not console_pass == "":
                console_pass = "passwd='" + console_pass + "'"

        xml += """<input type='mouse' bus='virtio'/>"""
        xml += """<input type='tablet' bus='virtio'/>"""
        xml += """
                <graphics type='%s' port='-1' autoport='yes' %s listen='%s'/>
                <console type='pty'/> """ % (graphics, console_pass, listen_addr)

        if qemu_ga:
            xml += """ <channel type='unix'>
                            <target type='virtio' name='org.qemu.guest_agent.0'/>
                       </channel>"""

        xml += """ <video>
                      <model type='%s'/>
                   </video>
              </devices>
            </domain>""" % video
        self._defineXML(xml)
