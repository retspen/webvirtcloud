from django.urls import path, include
from storages.views import storages, storage, get_volumes
from networks.views import networks, network
from secrets.views import secrets
from create.views import create_instance, create_instance_select_type
from interfaces.views import interfaces, interface
from computes.views import overview, compute_graph, computes, get_compute_disk_buses, get_compute_machine_types, get_dom_capabilities
from instances.views import instances
from nwfilters.views import nwfilter, nwfilters

urlpatterns = [
    path('', computes, name='computes'),
    path('<int:compute_id>/', include([
        path('', overview, name='overview'),
        path('statistics', compute_graph, name='compute_graph'),
        path('instances/', instances, name='instances'),
        path('storages/', storages, name='storages'),
        path('storage/<pool>/volumes', get_volumes, name='volumes'),
        path('storage/<pool>/', storage, name='storage'),
        path('networks/', networks, name='networks'),
        path('network/<pool>/', network, name='network'),
        path('interfaces/', interfaces, name='interfaces'),
        path('interface/<iface>/', interface, name='interface'),
        path('nwfilters/', nwfilters, name='nwfilters'),
        path('nwfilter/<nwfltr>/', nwfilter, name='nwfilter'),
        path('secrets/', secrets, name='secrets'),
        path('create/', create_instance_select_type, name='create_instance_select_type'),
        path('create/archs/<arch>/machines/<machine>', create_instance, name='create_instance'),
        path('archs/<arch>/machines', get_compute_machine_types, name='machines'),
        path('archs/<arch>/machines/<machine>/disks/<disk>/buses', get_compute_disk_buses, name='buses'),
        path('archs/<arch>/machines/<machine>/capabilities', get_dom_capabilities, name='domcaps'),
    ])),
]
