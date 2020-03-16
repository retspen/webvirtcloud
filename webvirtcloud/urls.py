from django.urls import include, path

from instances.views import index
from console.views import console
# from django.contrib import admin

urlpatterns = [
    path('', index, name='index'),

    path('instances/', include('instances.urls')),
    path('accounts/', include('accounts.urls')),
    path('computes/', include('computes.urls')),
    path('logs/', include('logs.urls')),
    path('datasource/', include('datasource.urls')),
    path('console/', console, name='console'),
    # url(r'^admin/', include(admin.site.urls)),
]
