# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure(2) do |config|
  config.vm.box = "ubuntu/trusty64"
  config.vm.hostname = "webvirtcloud"
  config.vm.network "private_network", ip: "192.168.33.10"
  config.vm.provision "shell", inline: <<-SHELL
     sudo sh /vagrant/dev/libvirt-bootstrap.sh
     sudo sed -i 's/auth_tcp = \"sasl\"/auth_tcp = \"none\"/g' /etc/libvirt/libvirtd.conf
     sudo service libvirt-bin restart
     sudo adduser vagrant libvirtd
     sudo apt-get -y install python-virtualenv python-dev python-lxml libvirt-dev zlib1g-dev
     virtualenv /vagrant/venv
     source /vagrant/venv/bin/activate
     pip install -r /vagrant/dev/requirements.txt
  SHELL
end
