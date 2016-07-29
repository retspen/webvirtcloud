from django.conf.urls import patterns, include, url
# from django.contrib import admin

urlpatterns = patterns('',
    url(r'^$', 'instances.views.index', name='index'),
    url(r'^instances/$', 'instances.views.instances', name='instances'),

    url(r'^instance/', include('instances.urls')),
    url(r'^accounts/', include('accounts.urls')),
    url(r'^computes/', include('computes.urls')),
    url(r'^logs/', include('logs.urls')),

    url(r'^compute/(?P<compute_id>[0-9]+)/storages/$',
        'storages.views.storages', name='storages'),
    url(r'^compute/(?P<compute_id>[0-9]+)/storage/(?P<pool>[\w\-\.\/]+)/$',
        'storages.views.storage', name='storage'),
    url(r'^compute/(?P<compute_id>[0-9]+)/networks/$',
        'networks.views.networks', name='networks'),
    url(r'^compute/(?P<compute_id>[0-9]+)/network/(?P<pool>[\w\-\.]+)/$',
        'networks.views.network', name='network'),
    url(r'^compute/(?P<compute_id>[0-9]+)/interfaces/$',
        'interfaces.views.interfaces', name='interfaces'),
    url(r'^compute/(?P<compute_id>[0-9]+)/interface/(?P<iface>[\w\-\.\:]+)/$',
        'interfaces.views.interface', name='interface'),
    url(r'^compute/(?P<compute_id>[0-9]+)/secrets/$',
        'secrets.views.secrets', name='secrets'),
    url(r'^compute/(?P<compute_id>[0-9]+)/create/$',
        'create.views.create_instance', name='create_instance'),

    url(r'^console/$', 'console.views.console', name='console'),
    # (r'^admin/', include(admin.site.urls)),
)
