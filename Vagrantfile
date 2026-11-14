# Two disposable compute nodes for the live tests (README: Running tests), so
# that migration runs between them: AlmaLinux 10 with nested KVM, set up by
# dev/libvirt-bootstrap.sh, with a SASL user for TCP and the host user's SSH
# key for root (SASL user wvc, password wvc-test). The empty second disk
# /dev/vdb is for the LVM tests (TEST_LIBVIRT_LVM_DEVICE); each also serves a
# 1 GiB iSCSI LUN on 127.0.0.1 for the iSCSI tests (TEST_LIBVIRT_ISCSI_TARGET),
# exports /srv/wvc-nfs to 127.0.0.1 for the NFS pool test (TEST_LIBVIRT_NFS_EXPORT),
# and accepts TLS logins (SASL) with a certificate from a throwaway CA.

# The CA is made here once; each compute signs its own certificate with it.
# The client certificate sits where libvirt looks with HOME=.vagrant/tls.
pki = File.join(__dir__, ".vagrant/tls/.pki/libvirt")
unless File.exist?(File.join(pki, "clientcert.pem"))
  # the host's openssl, not the one Vagrant puts first on PATH
  Vagrant::Util::Env.with_original_env do
    system("sh", "-ec", <<-SH, pki, exception: true)
      mkdir -p "$0" && cd "$0"
      openssl req -x509 -newkey rsa:3072 -nodes -keyout cakey.pem -out cacert.pem -days 365 -subj /CN=wvc-test-ca
      openssl req -new -newkey rsa:3072 -nodes -keyout clientkey.pem -subj /CN=wvc-test-client |
        openssl x509 -req -CA cacert.pem -CAkey cakey.pem -days 365 -out clientcert.pem
    SH
  end
end

Vagrant.configure(2) do |config|
  config.vm.box = "almalinux/10"
  %w[compute1 compute2].each do |name|
    config.vm.define(name) { |node| node.vm.hostname = "wvc-#{name}" }
  end
  config.vm.synced_folder ".", "/vagrant", disabled: true
  config.vm.provider :libvirt do |v|
    v.memory = 4096
    v.cpus = 2
    v.nested = true
    v.cpu_mode = "host-passthrough"
    v.video_type = "virtio"  # EL10 hosts have no cirrus
    v.storage :file, size: "4G"
  end
  # the bootstrap installs this checkout's gstfsd
  config.vm.provision "file", source: "dev", destination: "/tmp/wvc/dev"
  config.vm.provision "file", source: "conf", destination: "/tmp/wvc/conf"
  config.vm.provision "file", source: "~/.ssh/id_ed25519.pub", destination: "/tmp/wvc/key.pub"
  config.vm.provision "file", source: "#{pki}/cacert.pem", destination: "/tmp/wvc/cacert.pem"
  config.vm.provision "file", source: "#{pki}/cakey.pem", destination: "/tmp/wvc/cakey.pem"
  config.vm.provision "shell", inline: <<-SHELL
    set -e
    sh /tmp/wvc/dev/libvirt-bootstrap.sh
    virsh pool-info default > /dev/null 2>&1 || { virsh pool-define-as default dir --target /var/lib/libvirt/images && virsh pool-autostart default && virsh pool-start default; }
    echo wvc-test | saslpasswd2 -a libvirt -p wvc
    install -d -m 700 /root/.ssh
    cat /tmp/wvc/key.pub >> /root/.ssh/authorized_keys
    dnf -y install targetcli
    systemctl enable --now target
    T=iqn.2026-10.test.wvc:lun
    targetcli ls /iscsi/$T > /dev/null 2>&1 || {
      targetcli /backstores/fileio create wvc /var/lib/wvc-iscsi.img 1G
      targetcli /iscsi create $T
      targetcli /iscsi/$T/tpg1/portals delete 0.0.0.0 3260
      targetcli /iscsi/$T/tpg1/portals create 127.0.0.1 3260
      targetcli /iscsi/$T/tpg1/luns create /backstores/fileio/wvc
      targetcli /iscsi/$T/tpg1 set attribute generate_node_acls=1 demo_mode_write_protect=0
      targetcli saveconfig
    }
    dnf -y install nfs-utils
    install -d /srv/wvc-nfs
    echo "/srv/wvc-nfs 127.0.0.1(rw,no_root_squash)" > /etc/exports.d/wvc.exports
    systemctl enable --now nfs-server
    exportfs -r
    install -D -m 644 /tmp/wvc/cacert.pem /etc/pki/CA/cacert.pem
    install -d /etc/pki/libvirt/private
    echo "subjectAltName=IP:$(hostname -I | cut -d' ' -f1)" > /tmp/wvc/ext
    openssl req -new -newkey rsa:3072 -nodes -keyout /etc/pki/libvirt/private/serverkey.pem -subj /CN=$(hostname) |
      openssl x509 -req -CA /tmp/wvc/cacert.pem -CAkey /tmp/wvc/cakey.pem -days 365 -extfile /tmp/wvc/ext -out /etc/pki/libvirt/servercert.pem
    sed -i 's/^#auth_tls = "none"/auth_tls = "sasl"/' /etc/libvirt/virtproxyd.conf
    # a running service would keep the old settings and refuse a new socket
    systemctl stop virtproxyd.service
    systemctl enable --now virtproxyd-tls.socket
  SHELL
end
