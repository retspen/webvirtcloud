from django.conf import settings
from django.urls import include, path

from appsettings.views import appsettings
from console.views import console
from instances.views import index

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

if settings.DEBUG:
    try:
        import debug_toolbar

        urlpatterns += [
            path('__debug__/', include(debug_toolbar.urls)),
        ]
    except:
        pass
