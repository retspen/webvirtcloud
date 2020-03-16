from django.urls import path, re_path
from storages.views import storages, storage, get_volumes
from networks.views import networks, network
from secrets.views import secrets
from create.views import create_instance, create_instance_select_type
from interfaces.views import interfaces, interface
from computes.views import overview, compute_graph, computes, get_compute_disk_buses, get_compute_machine_types, get_dom_capabilities
from instances.views import instances
from nwfilters.views import nwfilter, nwfilters

urlpatterns = [
    path('', computes, name='computes'),
    re_path(r'^(?P<compute_id>[0-9]+)/$', overview, name='overview'),
    re_path(r'^(?P<compute_id>[0-9]+)/statistics$', compute_graph, name='compute_graph'),
    re_path(r'^(?P<compute_id>[0-9]+)/instances/$', instances, name='instances'),
    re_path(r'^(?P<compute_id>[0-9]+)/storages/$', storages, name='storages'),
    re_path(r'^(?P<compute_id>[0-9]+)/storage/(?P<pool>[\w\-\.\/]+)/volumes$', get_volumes, name='volumes'),
    re_path(r'^(?P<compute_id>[0-9]+)/storage/(?P<pool>[\w\-\.\/]+)/$', storage, name='storage'),
    re_path(r'^(?P<compute_id>[0-9]+)/networks/$', networks, name='networks'),
    re_path(r'^(?P<compute_id>[0-9]+)/network/(?P<pool>[\w\-\.]+)/$', network, name='network'),
    re_path(r'^(?P<compute_id>[0-9]+)/interfaces/$', interfaces, name='interfaces'),
    re_path(r'^(?P<compute_id>[0-9]+)/interface/(?P<iface>[\w\-\.\:]+)/$', interface, name='interface'),
    re_path(r'^(?P<compute_id>[0-9]+)/nwfilters/$', nwfilters, name='nwfilters'),
    re_path(r'^(?P<compute_id>[0-9]+)/nwfilter/(?P<nwfltr>[\w\-\.\:]+)/$', nwfilter, name='nwfilter'),
    re_path(r'^(?P<compute_id>[0-9]+)/secrets/$', secrets, name='secrets'),
    re_path(r'^(?P<compute_id>[0-9]+)/create/$', create_instance_select_type, name='create_instance_select_type'),
    re_path(r'^(?P<compute_id>[0-9]+)/create/archs/(?P<arch>[\w\-\.\/]+)/machines/(?P<machine>[\w\-\.\/]+)$', create_instance, name='create_instance'),
    re_path(r'^(?P<compute_id>[0-9]+)/archs/(?P<arch>[\w\-\.\/]+)/machines$', get_compute_machine_types, name='machines'),
    re_path(r'^(?P<compute_id>[0-9]+)/archs/(?P<arch>[\w\-\.\/]+)/machines/(?P<machine>[\w\-\.\/]+)/disks/(?P<disk>[\w\-\.\/]+)/buses$', get_compute_disk_buses, name='buses'),
    re_path(r'^(?P<compute_id>[0-9]+)/archs/(?P<arch>[\w\-\.\/]+)/machines/(?P<machine>[\w\-\.\/]+)/capabilities$', get_dom_capabilities, name='domcaps'),
]

