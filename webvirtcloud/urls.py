from django.conf.urls import patterns, include, url
from django.contrib import admin

urlpatterns = patterns('',
    url(r'^login/$', 'django.contrib.auth.views.login', {'template_name': 'login.html'}, name='login'),
    url(r'^logout/$', 'django.contrib.auth.views.logout', {'template_name': 'logout.html'}, name='logout'),

    url(r'^login/$', 'django.contrib.auth.views.login'),
    url(r'^logout/$', 'django.contrib.auth.views.logout'),

    url(r'^$', 'instances.views.index', name='index'),
    url(r'^instances$', 'instances.views.instances', name='instances'),
    url(r'^instance/(\d+)/([\w\-\.]+)/$', 'instances.views.instance', name='instance'),

    url(r'^computes/$', 'computes.views.computes', name='computes'),
    url(r'^compute/(\d+)/$', 'computes.views.compute', name='compute'),

    url(r'^storages/(\d+)/$', 'storages.views.storages', name='storages'),
    url(r'^storage/(\d+)/([\w\-\.]+)/$', 'storages.views.storage', name='storage'),

    url(r'^networks/(\d+)/$', 'networks.views.networks', name='networks'),
    url(r'^network/(\d+)/([\w\-\.]+)/$', 'networks.views.network', name='network'),

    url(r'^interfaces/(\d+)/$', 'interfaces.views.interfaces', name='interfaces'),
    url(r'^interface/(\d+)/([\w\.]+)$', 'interfaces.views.interface', name='interface'),

    url(r'^secret/(\d+)/$', 'secrets.views.secrets', name='secrets'),

    url(r'^users/$', 'users.views.users', name='users'),
    url(r'^user/(\d+)/$', 'users.views.user', name='user'),

    url(r'^console/$', 'console.views.console', name='console'),
    url(r'^create/(\d+)/$', 'create.views.create_instance', name='create_instance'),
    url(r'^logs/$', 'logs.views.showlogs', name='showlogs'),
    (r'^admin/', include(admin.site.urls)),
)
