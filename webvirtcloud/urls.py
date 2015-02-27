from django.conf.urls import patterns, include, url
from django.contrib import admin

urlpatterns = patterns('',
    # url(r'^login/$', 'django.contrib.auth.views.login', {'template_name': 'login.html'}, name='login'),
    url(r'^logout/$', 'django.contrib.auth.views.logout', {'template_name': 'logout.html'}, name='logout'),

    url(r'^login/$', 'django.contrib.auth.views.login'),
    url(r'^logout/$', 'django.contrib.auth.views.logout'),

    url(r'^$', 'instances.views.index', name='index'),
    url(r'^instances$', 'instances.views.instances', name='instances'),
    url(r'^instance/(\d+)/([\w\-\.]+)/$', 'instances.views.instance', name='instance'),

    url(r'^computes/$', 'computes.views.computes', name='computes'),
    url(r'^compute/(\d+)/$', 'computes.views.compute', name='compute'),

    # url(r'^storages/$', 'storages.views.storages', name='storages'),
    # url(r'^storage/(\d+)/([\w\-\.]+)/$', 'storages.views.storage', name='storage'),
    #
    # url(r'^networks/$', 'networks.views.networks', name='networks'),
    # url(r'^network/(\d+)/([\w\-\.]+)/$', 'networks.views.network', name='network'),
    #
    # url(r'^interfaces/$', 'interfaces.views.interfaces', name='interfaces'),
    # url(r'^interface/(\d+)/([\w\.]+)$', 'interfaces.views.interface', name='interface'),
    #
    # url(r'^secrets/$', 'secrets.views.secrets', name='secrets'),
    # url(r'^secret/(\d+)/([\w\.]+)$', 'secrets.views.secret', name='secret'),
    #
    # url(r'^accounts/$', 'accounts.views.accounts', name='accounts'),
    # url(r'^account/(\d+)/$', 'accounts.views.account', name='account'),
    #
    # url(r'^console/$', 'console.views.console', name='console'),
    # url(r'^create/(\d+)/$', 'create.views.create', name='create'),
    (r'^admin/', include(admin.site.urls)),
)
