from django.conf.urls import patterns, include, url
# from django.contrib import admin

urlpatterns = patterns('',
    url(r'^$', 'instances.views.index', name='index'),
    url(r'^instances/$', 'instances.views.instances', name='instances'),
    url(r'^instance/', include('instances.urls')),
    url(r'^accounts/', include('accounts.urls')),
    url(r'^computes/', include('computes.urls')),

    url(r'^compute/stgs/(?P<compute_id>[0-9]+)/$', 'storages.views.storages', name='storages'),
    url(r'^compute/stg/(?P<compute_id>[0-9]+)/(?P<pool>[\w\-\.]+)/$', 'storages.views.storage', name='storage'),

    url(r'^compute/nets/(?P<compute_id>[0-9]+)/$', 'networks.views.networks', name='networks'),
    url(r'^compute/net/(?P<compute_id>[0-9]+)/(?P<pool>[\w\-\.]+)/$', 'networks.views.network', name='network'),

    url(r'^compute/ifaces/(?P<compute_id>[0-9]+)/$', 'interfaces.views.interfaces', name='interfaces'),
    url(r'^compute/iface/(?P<compute_id>[0-9]+)/(?P<iface>[\w\-\.\:]+)/$', 'interfaces.views.interface', name='interface'),

    url(r'^compute/secret/(?P<compute_id>[0-9]+)/$', 'secrets.views.secrets', name='secrets'),

    url(r'^console/$', 'console.views.console', name='console'),
    url(r'^create/(?P<compute_id>[0-9]+)/$', 'create.views.create_instance', name='create_instance'),
    url(r'^logs/$', 'logs.views.showlogs', name='showlogs'),
    # (r'^admin/', include(admin.site.urls)),
)
