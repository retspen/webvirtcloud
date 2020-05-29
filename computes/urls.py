from secrets.views import secrets

from django.urls import path

from . import views
from create.views import create_instance, create_instance_select_type
from instances.views import instances
from interfaces.views import interface, interfaces
from networks.views import network, networks
from nwfilters.views import nwfilter, nwfilters
from storages.views import get_volumes, storage, storages

urlpatterns = [
    path('', views.computes, name='computes'),
    path('<int:compute_id>/', views.overview, name='overview'),
    path('<int:compute_id>/statistics/', views.compute_graph, name='compute_graph'),
    path('<int:compute_id>/instances/', instances, name='instances'),
    path('<int:compute_id>/storages/', storages, name='storages'),
    path('<int:compute_id>/storage/<str:pool>/volumes/', get_volumes, name='volumes'),
    path('<int:compute_id>/storage/<str:pool>/', storage, name='storage'),
    path('<int:compute_id>/networks/', networks, name='networks'),
    path('<int:compute_id>/network/<str:pool>/', network, name='network'),
    path('<int:compute_id>/interfaces/', interfaces, name='interfaces'),
    path('<int:compute_id>/interface/<str:iface>/', interface, name='interface'),
    path('<int:compute_id>/nwfilters/', nwfilters, name='nwfilters'),
    path('<int:compute_id>/nwfilter/<str:nwfltr>/', nwfilter, name='nwfilter'),
    path('<int:compute_id>/secrets/', secrets, name='secrets'),
    path('<int:compute_id>/create/', create_instance_select_type, name='create_instance_select_type'),
    path('<int:compute_id>/create/archs/<str:arch>/machines/<str:machine>/', create_instance, name='create_instance'),
    path('<int:compute_id>/archs/<str:arch>/machines/', views.get_compute_machine_types, name='machines'),
    path(
        '<int:compute_id>/archs/<str:arch>/machines/<str:machine>/disks/<str:disk>/buses/',
        views.get_compute_disk_buses,
        name='buses',
    ),
    path(
        '<int:compute_id>/archs/<str:arch>/machines/<str:machine>/capabilities/',
        views.get_dom_capabilities,
        name='domcaps',
    ),
]
