"""VM backups: the target pools and what a VM's backup holds (app vmbackups)."""

import hashlib
import os
import re

import libvirt
from django.utils.translation import gettext_noop
from lxml import etree

from vrtManager.connection import NVRAM_DIR, wvmConnect
from vrtManager.instance import PERSISTENT_XML, rewrite_for_new_vm, wvmInstance
from vrtManager.util import OperationError

# pools that keep their volumes as files in one directory
TARGET_TYPES = ("dir", "netfs")


def target_pool(conn, name, uuid=None):
    """The active dir or netfs pool name of conn's host; with uuid, only the
    pool a target registered, not another made since under its name."""
    try:
        pool = conn.get_storage(name)
        usable = (
            pool.isActive()
            and etree.fromstring(pool.XMLDesc(0)).get("type") in TARGET_TYPES
            and uuid in (None, pool.UUIDString())
        )
    except libvirt.libvirtError as err:
        if err.get_error_code() != libvirt.VIR_ERR_NO_STORAGE_POOL:
            raise
        usable = False
    if not usable:
        raise OperationError(
            gettext_noop(
                "Storage pool %(pool)s is not an active directory or NFS pool of this host, "
                "or not the one the backup target registered"
            ),
            pool=name,
        )
    return pool


def pool_space(pool):
    """{name, size, free, used_percent} of a pool, as the storage pages show
    it; refreshed first, as files may have changed outside libvirt."""
    pool.refresh(0)
    _state, size, used, free = pool.info()
    return {"name": pool.name(), "size": size, "free": free, "used_percent": used * 100 / size if size else 0}


class wvmBackup(wvmInstance):
    """The VM side of a backup."""

    def backup_plan(self):
        """What a backup of the VM copies, from its persistent definition:
        {"definition", "disks": [{dev, path, pool, format, capacity, allocation}],
        "nvram": path or None, "tpm": whether it has a TPM (shut off: its
        state is read by the job), "left_out": [{dev, why}]}. Refuses, naming
        why, a VM whose backup could not be restored as it is."""
        tree = etree.fromstring(self._XMLDesc(PERSISTENT_XML))
        name = self.instance.name()
        if self.instance.hasManagedSaveImage(0):
            raise OperationError(gettext_noop("%(vm)s has a saved state; start it or remove the saved state first"), vm=name)
        tpm = self.get_tpm()
        if tpm == "custom":
            raise OperationError(gettext_noop("%(vm)s has a TPM of its own settings (encryption, a state path or "
                                              "another backend); it cannot be backed up"), vm=name)
        if tpm and self.instance.state()[0] != libvirt.VIR_DOMAIN_SHUTOFF:
            raise OperationError(gettext_noop("%(vm)s has TPM state; shut it down to back it up"), vm=name)
        if tree.find("devices/filesystem") is not None:
            raise OperationError(gettext_noop("%(vm)s shares a host directory (filesystem); it cannot be backed up"), vm=name)
        if tree.xpath("devices/memory[@model='nvdimm' or @model='virtio-pmem']"):
            raise OperationError(gettext_noop("%(vm)s has a persistent memory device (a host file); it cannot be backed up"),
                                 vm=name)
        if tree.xpath("os/kernel|os/initrd|os/dtb"):
            raise OperationError(gettext_noop("%(vm)s boots a kernel file of the host; it cannot be backed up"), vm=name)
        if tree.xpath("devices/hostdev|devices/interface[@type='hostdev']"):
            raise OperationError(gettext_noop("%(vm)s has a host device; it cannot be backed up"), vm=name)

        disks, left_out = [], []
        for disk in tree.xpath("devices/disk"):
            dev = disk.find("target").get("dev")
            if disk.get("device") in ("cdrom", "floppy"):
                why = gettext_noop("CD-ROM: not copied") if disk.get("device") == "cdrom" else gettext_noop("Floppy: not copied")
                left_out.append({"dev": dev, "why": why})
                continue
            if disk.xpath("encryption|source/encryption"):
                raise OperationError(gettext_noop("Disk %(dev)s is encrypted; it cannot be backed up"), dev=dev)
            path = disk.xpath("string(source/@file)")
            if disk.get("type") != "file" or not path:
                raise OperationError(gettext_noop("Disk %(dev)s is not a file; it cannot be backed up"), dev=dev)
            if disk.find("shareable") is not None:
                raise OperationError(gettext_noop("Disk %(dev)s is shareable; it cannot be backed up"), dev=dev)
            disk_format = disk.xpath("string(driver/@type)") or "raw"
            if disk_format not in ("qcow2", "raw"):
                raise OperationError(gettext_noop("Disk %(dev)s is %(format)s; only qcow2 and raw disks are backed up"),
                              dev=dev, format=disk_format)
            try:
                vol = self.get_volume_by_path(path)
            except libvirt.libvirtError as err:
                if err.get_error_code() != libvirt.VIR_ERR_NO_STORAGE_VOL:
                    raise
                raise OperationError(gettext_noop("Disk %(dev)s (%(path)s) is in no storage pool of the host; it cannot be backed up"),
                              dev=dev, path=path) from err
            info = vol.info()
            disks.append({"dev": dev, "path": path, "pool": vol.storagePoolLookupByVolume().name(),
                          "format": disk_format, "capacity": info[1],
                          "allocation": min(info[1], self._chain_allocation(vol))})

        if self.instance.state()[0] != libvirt.VIR_DOMAIN_SHUTOFF:
            # a running VM's disks are copied: the definition kept must name the same ones
            live = etree.fromstring(self._XMLDesc(0))
            copied = [(d["dev"], d["path"]) for d in disks]
            running = [(d.find("target").get("dev"), d.xpath("string(source/@file)"))
                       for d in live.xpath("devices/disk[not(@device='cdrom' or @device='floppy')]")]
            if copied != running:
                changed = sorted({dev for dev, _path in set(copied) ^ set(running)})
                raise OperationError(gettext_noop("Disks %(devs)s change at the next start; back the VM up after it restarts"),
                              devs=", ".join(changed))

        # a block device's or network NVRAM is named too: it is refused below
        nvram = (tree.xpath("string(os/nvram/source/@file|os/nvram/source/@dev|os/nvram/source/@name)")
                 or (tree.findtext("os/nvram") or "").strip() or None)
        if nvram and os.path.dirname(nvram) != NVRAM_DIR:
            raise OperationError(gettext_noop("The NVRAM file %(path)s is not in libvirt's NVRAM directory %(dir)s and cannot be copied"),
                          path=nvram, dir=NVRAM_DIR)
        return {"definition": etree.tostring(tree).decode(), "disks": disks, "nvram": nvram, "tpm": bool(tpm),
                "left_out": left_out}

    def copy_disk_offline(self, disk, pool, name, owner_uid, owner_gid):
        """A shut-off VM's disk copied into the target pool, flat, in its
        format (libvirt's createXMLFrom). Returns the copy's path."""
        return self.get_wvmStorage(pool).clone_volume(
            self.get_volume_by_path(disk["path"]), name, vol_fmt=disk["format"],
            disk_owner_uid=owner_uid, disk_owner_gid=owner_gid,
        )

    def make_live_targets(self, disks, pool, names, owner_uid, owner_gid, backing=None):
        """The empty volumes a running VM's push backup writes into, in the
        target pool, each on its backing file of backing ({dev: file name},
        an incremental backup's); the targets begin_clone_backup takes."""
        targets = []
        for disk in disks:
            target = {"dev": disk["dev"], "pool": pool, "name": names[disk["dev"]],
                      "capacity": disk["capacity"], "format": disk["format"], "backing": (backing or {}).get(disk["dev"])}
            target["path"] = self.create_clone_target(target, owner_uid, owner_gid)
            targets.append(target)
        return targets

    def read_nvram(self, path):
        """The bytes of the VM's NVRAM file; None when it was never made (the
        VM never started)."""
        with self._nvram_pool() as pool:
            vol = self._find_volume(pool, os.path.basename(path))
            return None if vol is None else self.download_volume(vol)

    def _chain_allocation(self, vol):
        """The bytes a disk's volume and the files below it hold: its backup
        copies them flat."""
        total, seen = 0, set()
        while vol is not None and vol.path() not in seen:
            seen.add(vol.path())
            total += vol.info()[2]
            below = etree.fromstring(vol.XMLDesc(0)).findtext("backingStore/path")
            try:
                vol = self.get_volume_by_path(below) if below else None
            except libvirt.libvirtError:
                vol = None  # in no pool: counted by its own size only
        return total

    def checkpoint_sizes(self, name, devs):
        """The bytes each disk of devs changed since the checkpoint name,
        {dev: size}, or None when it cannot be an incremental backup's base:
        not on this host, or a disk without a bitmap of known size (libvirt
        leaves the size out for a lost or invalid bitmap)."""
        try:
            xml = self.instance.checkpointLookupByName(name).getXMLDesc(libvirt.VIR_DOMAIN_CHECKPOINT_XML_SIZE)
        except libvirt.libvirtError as err:
            if err.get_error_code() != libvirt.VIR_ERR_NO_DOMAIN_CHECKPOINT:
                raise
            return None
        sizes = {d.get("name"): int(d.get("size")) for d in etree.fromstring(xml).xpath("disks/disk[@checkpoint='bitmap' and @size]")}
        return {dev: sizes[dev] for dev in devs} if set(devs) <= set(sizes) else None

    def prune_checkpoints(self, keep, known, devs):
        """Deletes the backups' checkpoints (wvc-) of a running VM but those
        of keep, and their bitmaps. known: {name: creation time} of the
        checkpoints the panel made; one libvirt no longer lists (after a
        migration) is redefined first so that its bitmap goes too."""
        listed = {cp.getName() for cp in self.instance.listAllCheckpoints(0)}
        for name in sorted(({n for n in listed if n.startswith("wvc-")} | set(known)) - set(keep)):
            if name not in listed:
                disks = "".join(f"<disk name='{dev}' checkpoint='bitmap' bitmap='{name}'/>" for dev in devs)
                try:
                    self.instance.checkpointCreateXML(
                        f"<domaincheckpoint><name>{name}</name><creationTime>{known[name]}</creationTime>"
                        f"<disks>{disks}</disks></domaincheckpoint>", libvirt.VIR_DOMAIN_CHECKPOINT_CREATE_REDEFINE)
                except libvirt.libvirtError:
                    continue  # nothing of it is left to delete
            checkpoint = self.instance.checkpointLookupByName(name)
            try:
                checkpoint.delete(0)
            except libvirt.libvirtError:  # its bitmap is gone: only the record is left
                checkpoint.delete(libvirt.VIR_DOMAIN_CHECKPOINT_DELETE_METADATA_ONLY)

    def read_tpm(self):
        """The shut-off VM's TPM state files: {name: bytes}, {} when it never
        started. swtpm's .lock is not state."""
        with self._tpm_pool(self.instance.UUIDString()) as pool:
            if pool is None:
                return {}
            return {name: self.download_volume(pool.storageVolLookupByName(name))
                    for name in sorted(pool.listVolumes()) if not name.startswith(".")}


def backup_prefix(vm_name, uuid):
    """The start of a backup's file names in the target pool: its VM's name,
    so the directory shows whose it is, and the backup's UUID."""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", vm_name)[:64].lstrip(".-") or "vm"
    return f"{name}-{uuid}"


def backup_file_names(prefix, disks, nvram):
    """The names of a backup's files in the target pool."""
    return {
        "disks": {d["dev"]: f"{prefix}-{d['dev']}.{'qcow2' if d['format'] == 'qcow2' else 'raw'}" for d in disks},
        "nvram": f"{prefix}-nvram.fd" if nvram else None,
        "tpm": f"{prefix}-tpm-",  # and the state file's name
        "domain": f"{prefix}-domain.xml",
        "manifest": f"{prefix}-manifest.json",
    }


def check_target_space(pool, disks, free_percent, free_min_gib):
    """The target keeps the disks' virtual capacity plus free_percent of
    it, at least free_min_gib GiB, free (the snapshots' and clones' rule)."""
    size = sum(d["capacity"] for d in disks)
    needed = size + max(size * free_percent / 100, free_min_gib * 1024**3)
    pool.refresh(0)
    free = pool.info()[3]
    if free < needed:
        raise OperationError(gettext_noop(
            "Storage pool %(pool)s has %(free).1f GiB free; the backup needs %(size).1f GiB (the copied disks, "
            "plus %(percent)g%% of them, at least %(minimum)g GiB)"),
            pool=pool.name(), free=free / 1024**3, size=needed / 1024**3, percent=free_percent, minimum=free_min_gib)


def put_file(conn, pool, name, data, owner, mode="0644"):
    """Writes a small file of a backup into the target pool as owner (uid,
    gid) with mode, replacing one of that name, and reads it back. Returns
    its SHA-256."""
    remove_files(pool, [name])
    vol = conn.upload_volume(pool, name, data, owner=owner, mode=mode)
    if conn.download_volume(vol) != data:
        vol.delete(0)
        raise OperationError(gettext_noop("The file %(name)s read back from the backup target differs from the one written"), name=name)
    return hashlib.sha256(data).hexdigest()


def get_file(conn, pool, name):
    return conn.download_volume(pool.storageVolLookupByName(name))


def remove_files(pool, names):
    """Deletes the volumes names of pool; missing ones are passed over."""
    for name in names:
        vol = wvmConnect._find_volume(pool, name)
        if vol is not None:
            vol.delete(0)


def volume_exists(pool, name):
    return wvmConnect._find_volume(pool, name) is not None


MANIFEST_NAME = re.compile(r"-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-manifest\.json$")


def manifest_names(pool):
    pool.refresh(0)
    return sorted(name for name in pool.listVolumes() if MANIFEST_NAME.search(name))


def set_disk_sources(tree, disks):
    """Each disk of the definition tree a restored file (disks: {dev: (path,
    format)}), with nothing of the old one's chain."""
    for disk in tree.xpath("devices/disk[@device='disk']"):
        path, disk_format = disks[disk.find("target").get("dev")]
        disk.set("type", "file")
        for old in disk.xpath("source|backingStore"):
            disk.remove(old)
        driver = disk.find("driver")
        if driver is None:
            driver = etree.SubElement(disk, "driver", name="qemu")
        driver.set("type", disk_format)
        source = etree.Element("source", file=path)
        disk.insert(list(disk).index(driver) + 1, source)


def restore_over_definition(definition, disks):
    """The VM's own definition with its disks the restored files: the rest of
    it (devices, MACs, NVRAM path) is the VM's current one, but for a new
    generation ID, as the guest is rolled back."""
    tree = etree.fromstring(definition)
    set_disk_sources(tree, disks)
    if (genid := tree.find("genid")) is not None:
        genid.text = None  # libvirt makes a new one
    return etree.tostring(tree).decode()


def restore_definition(definition, *, name, uuid, macs, disks, nvram, connect):
    """A backup's kept definition made a new VM's: rewrite_for_new_vm's
    changes (macs: one per NIC, in order), its media ejected, a new generation ID, each disk's
    source the restored file (disks: {dev: (path, format)}) with nothing of
    the old one's chain, the NVRAM file at nvram, and each NIC's link down
    unless connect: the restored guest keeps the VM's addresses and names."""
    tree = etree.fromstring(definition)
    clone_data = {"name": name, "clone-title": tree.findtext("title") or "",
                  "clone-description": tree.findtext("description") or "",
                  **{f"clone-net-mac-{number}": mac for number, mac in enumerate(macs)}}
    rewrite_for_new_vm(tree, clone_data, uuid)
    # media are not in the backup: the restore host may not have them, and the VM would not start
    for source in tree.xpath("devices/disk[@device='cdrom' or @device='floppy']/source"):
        source.getparent().remove(source)
    if (genid := tree.find("genid")) is not None:
        genid.text = None  # libvirt makes a new one
    set_disk_sources(tree, disks)
    if (element := tree.find("os/nvram")) is not None:
        if element.find("source") is not None:
            element.find("source").set("file", nvram)
        else:
            element.text = nvram
    if not connect:
        for interface in tree.findall("devices/interface"):
            link = interface.find("link")
            if link is None:
                link = etree.SubElement(interface, "link")
            link.set("state", "down")
    return etree.tostring(tree).decode()


def check_restore_host(conn, definition):
    """Refuses a host that cannot run the backup's definition: its emulator,
    machine type, firmware and TPM, the networks, bridges and network filters
    its NICs name."""
    tree = etree.fromstring(definition)
    emulator = tree.findtext("devices/emulator")
    os_type = tree.find("os/type")
    arch, machine = os_type.get("arch"), os_type.get("machine")
    try:
        caps = etree.fromstring(conn.wvm.getDomainCapabilities(emulator, arch, machine, tree.get("type"), 0))
    except libvirt.libvirtError as err:
        raise OperationError(gettext_noop("This host cannot run the VM's emulator %(emulator)s with machine type %(machine)s: %(error)s"),
                             emulator=emulator, machine=machine, error=err) from err
    loader = (tree.findtext("os/loader") or "").strip()
    if loader and loader not in caps.xpath("os/loader/value/text()"):
        raise OperationError(gettext_noop("This host has no firmware %(loader)s"), loader=loader)
    if (tpm := tree.find("devices/tpm")) is not None:
        offered = "devices/tpm[@supported='yes']/enum[@name='{}']/value/text()"
        if ("emulator" not in caps.xpath(offered.format("backendModel"))
                or "2.0" not in caps.xpath(offered.format("backendVersion"))
                or tpm.get("model") not in caps.xpath(offered.format("model"))):
            raise OperationError(gettext_noop("This host offers no TPM 2.0 %(model)s: install swtpm on it"),
                                 model=tpm.get("model"))
    for network in sorted(set(tree.xpath("devices/interface[@type='network']/source/@network")) - set(conn.get_networks())):
        raise OperationError(gettext_noop("This host has no network %(name)s"), name=network)
    for bridge in sorted(set(tree.xpath("devices/interface[@type='bridge']/source/@bridge")) - set(conn.get_ifaces())):
        raise OperationError(gettext_noop("This host has no bridge %(name)s"), name=bridge)
    for nwfilter in sorted(set(tree.xpath("devices/interface/filterref/@filter")) - set(conn.get_nwfilters())):
        raise OperationError(gettext_noop("This host has no network filter %(name)s"), name=nwfilter)
