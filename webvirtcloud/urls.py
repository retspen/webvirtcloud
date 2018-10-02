from django.conf.urls import include, url

from instances.views import index
from console.views import console
# from django.contrib import admin

urlpatterns = [
    url(r'^$', index, name='index'),

    url(r'^instances/', include('instances.urls')),
    url(r'^accounts/', include('accounts.urls')),
    url(r'^computes/', include('computes.urls')),
    url(r'^logs/', include('logs.urls')),
    url(r'^datasource/', include('datasource.urls')),


    url(r'^console/$', console, name='console'),
    # (r'^admin/', include(admin.site.urls)),
]
