from django.conf.urls import url
from storages.views import storages, storage, get_volumes
from networks.views import networks, network
from secrets.views import secrets
from create.views import create_instance, create_instance_select_type
from interfaces.views import interfaces, interface
from computes.views import overview, compute_graph, computes, get_compute_disk_buses, get_compute_machine_types, get_dom_capabilities
from instances.views import instances
from nwfilters.views import nwfilter, nwfilters

urlpatterns = [
    url(r'^/', computes, name='computes'),
    url(r'^(?P<compute_id>[0-9]+)/$', overview, name='overview'),
    url(r'^(?P<compute_id>[0-9]+)/statistics$', compute_graph, name='compute_graph'),
    url(r'^(?P<compute_id>[0-9]+)/instances/$', instances, name='instances'),
    url(r'^(?P<compute_id>[0-9]+)/storages/$', storages, name='storages'),
    url(r'^(?P<compute_id>[0-9]+)/storage/(?P<pool>[\w\-\.\/]+)/volumes$', get_volumes, name='volumes'),
    url(r'^(?P<compute_id>[0-9]+)/storage/(?P<pool>[\w\-\.\/]+)/$', storage, name='storage'),
    url(r'^(?P<compute_id>[0-9]+)/networks/$', networks, name='networks'),
    url(r'^(?P<compute_id>[0-9]+)/network/(?P<pool>[\w\-\.]+)/$', network, name='network'),
    url(r'^(?P<compute_id>[0-9]+)/interfaces/$', interfaces, name='interfaces'),
    url(r'^(?P<compute_id>[0-9]+)/interface/(?P<iface>[\w\-\.\:]+)/$', interface, name='interface'),
    url(r'^(?P<compute_id>[0-9]+)/nwfilters/$', nwfilters, name='nwfilters'),
    url(r'^(?P<compute_id>[0-9]+)/nwfilter/(?P<nwfltr>[\w\-\.\:]+)/$', nwfilter, name='nwfilter'),
    url(r'^(?P<compute_id>[0-9]+)/secrets/$', secrets, name='secrets'),
    url(r'^(?P<compute_id>[0-9]+)/create/$', create_instance_select_type, name='create_instance_select_type'),
    url(r'^(?P<compute_id>[0-9]+)/create/archs/(?P<arch>[\w\-\.\/]+)/machines/(?P<machine>[\w\-\.\/]+)$', create_instance, name='create_instance'),
    url(r'^(?P<compute_id>[0-9]+)/archs/(?P<arch>[\w\-\.\/]+)/machines$', get_compute_machine_types, name='machines'),
    url(r'^(?P<compute_id>[0-9]+)/archs/(?P<arch>[\w\-\.\/]+)/machines/(?P<machine>[\w\-\.\/]+)/disks/(?P<disk>[\w\-\.\/]+)/buses$', get_compute_disk_buses, name='buses'),
    url(r'^(?P<compute_id>[0-9]+)/archs/(?P<arch>[\w\-\.\/]+)/machines/(?P<machine>[\w\-\.\/]+)/capabilities$', get_dom_capabilities, name='domcaps'),
]
