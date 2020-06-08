from django.urls import include, path

from instances.views import index
from console.views import console
from appsettings.views import appsettings

urlpatterns = [
    path('', index, name='index'),
    path('admin/', include(('admin.urls', 'admin'), namespace='admin')),
    path('accounts/', include('accounts.urls')),
    path('appsettings/', appsettings, name='appsettings'),
    path('computes/', include('computes.urls')),
    path('console/', console, name='console'),
    path('datasource/', include('datasource.urls')),
    path('instances/', include('instances.urls')),
    path('i18n/', include('django.conf.urls.i18n')),
    path('logs/', include('logs.urls')),
]
