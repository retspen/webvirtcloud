from django.urls import path, include

from . import views
from create.views import create_instance, create_instance_select_type
from instances.views import instances
from interfaces.views import interface, interfaces
from networks.views import network, networks
from nwfilters.views import nwfilter, nwfilters
from secrets.views import secrets
from storages.views import get_volumes, storage, storages

urlpatterns = [
    path('', views.computes, name='computes'),
    path('<int:compute_id>/', include([
        path('', views.overview, name='overview'),
        path('statistics', views.compute_graph, name='compute_graph'),
        path('instances/', instances, name='instances'),
        path('storages/', storages, name='storages'),
        path('storage/<str:pool>/volumes', get_volumes, name='volumes'),
        path('storage/<str:pool>/', storage, name='storage'),
        path('networks/', networks, name='networks'),
        path('network/<pool>/', network, name='network'),
        path('interfaces/', interfaces, name='interfaces'),
        path('interface/<str:iface>/', interface, name='interface'),
        path('nwfilters/', nwfilters, name='nwfilters'),
        path('nwfilter/<str:nwfltr>/', nwfilter, name='nwfilter'),
        path('secrets/', secrets, name='secrets'),
        path('create/', create_instance_select_type,
             name='create_instance_select_type'),
        path('create/archs/<str:arch>/machines/<str:machine>',
             create_instance, name='create_instance'),
        path('archs/<str:arch>/machines',
             views.get_compute_machine_types, name='machines'),
        path('archs/<str:arch>/machines/<str:machine>/disks/<str:disk>/buses',
             views.get_compute_disk_buses, name='buses'),
        path('archs/<str:arch>/machines/<str:machine>/capabilities',
             views.get_dom_capabilities, name='domcaps'),
    ])),
]
