from django.conf.urls import include, url

from instances.views import instances, instance, index
from storages.views import storages, storage
from networks.views import networks, network
from secrets.views import secrets
from create.views import create_instance
from interfaces.views import interfaces, interface
from console.views import console
from nwfilters.views import nwfilters, nwfilter
# from django.contrib import admin

urlpatterns = [
    url(r'^$', index, name='index'),
    url(r'^instances/$', instances, name='instances'),

    url(r'^instance/', include('instances.urls')),
    url(r'^accounts/', include('accounts.urls')),
    url(r'^computes/', include('computes.urls')),
    url(r'^logs/', include('logs.urls')),
    url(r'^datasource/', include('datasource.urls')),

    url(r'^compute/(?P<compute_id>[0-9]+)/storages/$', storages, name='storages'),
    url(r'^compute/(?P<compute_id>[0-9]+)/storage/(?P<pool>[\w\-\.\/]+)/$', storage, name='storage'),
    url(r'^compute/(?P<compute_id>[0-9]+)/networks/$', networks, name='networks'),
    url(r'^compute/(?P<compute_id>[0-9]+)/network/(?P<pool>[\w\-\.]+)/$', network, name='network'),
    url(r'^compute/(?P<compute_id>[0-9]+)/interfaces/$', interfaces, name='interfaces'),
    url(r'^compute/(?P<compute_id>[0-9]+)/interface/(?P<iface>[\w\-\.\:]+)/$', interface, name='interface'),
    url(r'^compute/(?P<compute_id>[0-9]+)/nwfilters/$', nwfilters, name='nwfilters'),
    url(r'^compute/(?P<compute_id>[0-9]+)/nwfilter/(?P<nwfltr>[\w\-\.\:]+)/$', nwfilter, name='nwfilter'),
    url(r'^compute/(?P<compute_id>[0-9]+)/secrets/$', secrets, name='secrets'),
    url(r'^compute/(?P<compute_id>[0-9]+)/create/$', create_instance, name='create_instance'),


    url(r'^console/$', console, name='console'),
    # (r'^admin/', include(admin.site.urls)),
]
