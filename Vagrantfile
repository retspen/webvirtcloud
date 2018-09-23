# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure(2) do |config|
  config.vm.box = "bento/centos-7.5"
  config.ssh.insert_key = false
  config.vm.provision :shell, path: "devenv/vagrant/bootstrap.sh"
  config.vm.network "private_network", ip: "192.168.250.254", auto_config: false
  config.vm.network "private_network", ip: "10.16.0.254", auto_config: false
  config.vm.network "forwarded_port", guest: 9090, host: 9090
  config.vm.network "forwarded_port", guest: 16509, host: 16509

  (0..1 - 1).each do |i|
    config.vm.define "node#{i}" do |kvm|
      kvm.vm.hostname = "node#{i}"
      kvm.vm.provider :virtualbox do |vb|
        vb.cpus = "2"
        vb.memory = "4096"
      end
    end
  
  end
end
