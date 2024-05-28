# Ubuntu Service Files

I choose to install this service on Ubuntu 22.04

The process is not fully documented but I wanted to contribute the service files

The file webvirt is beeing installed into /etc/default/webvirt and allows you to easily change the location of the webvirtcloud installation path

The PATH variable being set for these services includes /usr/bin which contains the ssh executable. That is being used by webvirt-cloud and webvirt-novncd

Should the executable be located in another location please adjust the path

The error you should be seeing is "ssh executable not found"


