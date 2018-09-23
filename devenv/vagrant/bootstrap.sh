#!/usr/bin/env bash
set -e

echo 'centos' | sudo tee -a /etc/yum/vars/contentdir
sudo yum -y install bash-completion net-tools telnet

# Install libvirt packages
sudo yum -y install epel-release centos-release-qemu-ev
sudo yum -y install qemu-kvm libvirt bridge-utils xmlstarlet python-libguestfs libguestfs-tools libguestfs-rescue libguestfs-winsupport libguestfs-bash-completion cyrus-sasl-md5
sudo systemctl start libvirtd
sudo systemctl enable libvirtd

# Setup libvirt
sudo sed -i 's/#LIBVIRTD_ARGS/LIBVIRTD_ARGS/g' /etc/sysconfig/libvirtd
sudo sed -i 's/#listen_tls/listen_tls/g' /etc/libvirt/libvirtd.conf
sudo sed -i 's/#listen_tcp/listen_tcp/g' /etc/libvirt/libvirtd.conf
sudo sed -i 's/#auth_tcp = \"sasl\"/auth_tcp = \"none\"/g' /etc/libvirt/libvirtd.conf
sudo sed -i 's/#LIBVIRTD_ARGS/LIBVIRTD_ARGS/g' /etc/sysconfig/libvirtd
sudo sed -i 's/: gssapi/: digest-md5/g' /etc/sasl2/libvirt.conf
sudo sed -i 's/#sasldb_path/sasldb_path/g' /etc/sasl2/libvirt.conf

sudo cp -rf /vagrant/devenv/vagrant/etc/libvirt/hooks /etc/libvirt/
sudo chmod +x /etc/libvirt/hooks/qemu

sudo mkdir /mnt/backups
sudo mkdir /var/lib/libvirt/isos

sudo virsh pool-define /vagrant/devenv/vagrant/etc/libvirt/pools/images.xml
sudo virsh pool-define /vagrant/devenv/vagrant/etc/libvirt/pools/backups.xml
sudo virsh pool-define /vagrant/devenv/vagrant/etc/libvirt/pools/isos.xml
sudo virsh pool-start images
sudo virsh pool-start backups
sudo virsh pool-start isos
sudo virsh pool-autostart images
sudo virsh pool-autostart backups
sudo virsh pool-autostart isos

sudo virsh net-destroy default
sudo virsh net-undefine default
sudo virsh net-define /vagrant/devenv/vagrant/etc/libvirt/networks/private.xml
sudo virsh net-define /vagrant/devenv/vagrant/etc/libvirt/networks/public.xml
sudo virsh net-start private
sudo virsh net-start public
sudo virsh net-autostart private
sudo virsh net-autostart public

sudo virsh nwfilter-define /vagrant/devenv/vagrant/etc/libvirt/nwfilters/allow-incoming-ipv6.xml
sudo virsh nwfilter-define /vagrant/devenv/vagrant/etc/libvirt/nwfilters/no-ipv6-spoofing.xml
sudo virsh nwfilter-define /vagrant/devenv/vagrant/etc/libvirt/nwfilters/clean-traffic-ipv6.xml

sudo systemctl restart libvirtd

# Sysctl
sudo cp /vagrant/devenv/vagrant/etc/sysctl.d/99-libvirt.conf /etc/sysctl.d/99-libvirt.conf
sudo sysctl -p

# Networking
sudo cp /vagrant/devenv/vagrant/etc/sysconfig/network-scripts/* /etc/sysconfig/network-scripts/
sudo brctl addbr br-ext
sudo ifconfig br-ext up
sudo brctl addbr br-int
sudo ifconfig br-int up
sudo systemctl restart network

# FirewallD
sudo systemctl enable firewalld
sudo systemctl restart firewalld
sudo firewall-cmd --permanent --direct --add-rule ipv4 filter FORWARD 1 -m physdev --physdev-is-bridged -j ACCEPT
sudo firewall-cmd --permanent --direct --add-rule ipv4 nat POSTROUTING 0 -i br-ext -d 10.255.0.0/16 -j MASQUERADE
sudo firewall-cmd --permanent --direct --add-rule ipv4 nat PREROUTING 0 -i br-ext -s 169.254.0.0/16 -d 169.254.169.254 -p tcp --dport 80 -j REDIRECT --to-ports 8887
sudo firewall-cmd --permanent --direct --add-rule ipv4 nat PREROUTING 0 -i br-ext ! -s 169.254.0.0/16 -d 169.254.169.254/32 -p tcp -m tcp --dport 80 -j DNAT --to-destination 10.0.2.2:8000
sudo firewall-cmd --permanent --zone=trusted --add-source=10.0.2.2/24
sudo firewall-cmd --permanent --zone=trusted --add-source=169.254.0.0/16
sudo firewall-cmd --reload

# Prometheus Server
echo "Downloading and installing prometheus server..."
curl -L https://github.com/prometheus/prometheus/releases/download/v2.3.2/prometheus-2.3.2.linux-amd64.tar.gz -o /tmp/prometheus-2.3.2.linux-amd64.tar.gz > /dev/null 2>&1
tar -zxf /tmp/prometheus-2.3.2.linux-amd64.tar.gz -C /opt/
sudo cp /vagrant/devenv/vagrant/opt/prometheus/prometheus.yml /opt/prometheus-2.3.2.linux-amd64/
sudo cp /vagrant/devenv/vagrant/opt/prometheus/prometheus.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable prometheus
sudo systemctl start prometheus

# Prometheus Libvirt Exporter
echo "Downloading and installing prometheus libvirt exporter..."
curl -L https://github.com/retspen/libvirt_exporter/releases/download/0.1.0/libvirt_exporter-0.1.0.linux-amd64.tar.gz -o /tmp/libvirt_exporter-0.1.0.linux-amd64.tar.gz > /dev/null 2>&1
tar -zxf /tmp/libvirt_exporter-0.1.0.linux-amd64.tar.gz -C /opt/
sudo cp /vagrant/devenv/vagrant/opt/libvirt_exporter/libvirt_exporter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable libvirt_exporter
sudo systemctl start libvirt_exporter

# NTP
sudo yum -y install ntp ntpdate ntp-doc
sudo systemctl enable ntpd
sudo systemctl start ntpd

# Upgrade system
sudo yum -y upgrade
