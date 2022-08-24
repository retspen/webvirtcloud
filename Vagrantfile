# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure(2) do |config|
  # Default machine, if name not specified...
  config.vm.define "dev", primary: true do |dev|
    dev.vm.box =  "ubuntu/bionic64"
    dev.vm.hostname = "webvirtcloud"
    dev.vm.network "private_network", ip: "192.168.33.10"
    dev.vm.provision "shell", inline: <<-SHELL
     sudo sh /vagrant/dev/libvirt-bootstrap.sh
     sudo sed -i 's/auth_tcp = \"sasl\"/auth_tcp = \"none\"/g' /etc/libvirt/libvirtd.conf
     sudo service libvirt-bin restart
     sudo adduser vagrant libvirtd
     sudo apt-get -y install python3-virtualenv virtualenv python3-pip python3-dev python3-lxml libvirt-dev zlib1g-dev python3-guestfs
     virtualenv -p python3 /vagrant/venv
     source /vagrant/venv/bin/activate
     pip3 install -r /vagrant/dev/requirements.txt
    SHELL
  end
  # To start this machine run "vagrant up prod"
  # To enter this machine run "vagrant ssh prod"
  config.vm.define "prod",  autostart: false do |prod|
    prod.vm.box = "ubuntu/bionic64"
    prod.vm.hostname = "webvirtcloud"
    prod.vm.network "private_network", ip: "192.168.33.11"
    prod.vm.network "forwarded_port", guest: 80, host: 8081
    #prod.vm.synced_folder ".", "/srv/webvirtcloud"
    prod.vm.provision "shell", inline: <<-SHELL
     sudo mkdir /srv/webvirtcloud
     sudo cp -R /vagrant/* /srv/webvirtcloud
     sudo sh /srv/webvirtcloud/dev/libvirt-bootstrap.sh
     sudo sed -i 's/auth_tcp = \"sasl\"/auth_tcp = \"none\"/g' /etc/libvirt/libvirtd.conf
     sudo service libvirt-bin restart
     sudo adduser vagrant libvirtd
     sudo chown -R vagrant:vagrant /srv/webvirtcloud
     sudo apt-get -y install python3-virtualenv python3-dev python3-lxml python3-pip virtualenv libvirt-dev zlib1g-dev libxslt1-dev nginx supervisor libsasl2-modules gcc pkg-config python3-guestfs
     virtualenv -p python3 /srv/webvirtcloud/venv
     source /srv/webvirtcloud/venv/bin/activate
     pip3 install -r /srv/webvirtcloud/requirements.txt
     sudo cp /srv/webvirtcloud/conf/supervisor/webvirtcloud.conf /etc/supervisor/conf.d
     sudo cp /srv/webvirtcloud/conf/nginx/webvirtcloud.conf /etc/nginx/conf.d
     sudo cp /srv/webvirtcloud/webvirtcloud/settings.py.template /srv/webvirtcloud/webvirtcloud/settings.py
     sudo sed "s/SECRET_KEY = ''/SECRET_KEY = '"`python3 /srv/webvirtcloud/conf/runit/secret_generator.py`"'/" -i /srv/webvirtcloud/webvirtcloud/settings.py
     python3 /srv/webvirtcloud/manage.py makemigrations
     python3 /srv/webvirtcloud/manage.py migrate
     python3 /srv/webvirtcloud/manage.py collectstatic --noinput
     sudo rm /etc/nginx/sites-enabled/default
     sudo chown -R www-data:www-data /srv/webvirtcloud
     sudo service nginx restart
     sudo service supervisor restart
    SHELL
  end
end


