from virtsecrets.views import secrets

from django.urls import include, path
from interfaces.views import interface, interfaces
from networks.views import network, networks
from nwfilters.views import nwfilter, nwfilters
from storages.views import create_volume, get_volumes, storage, storages

from . import forms, views

urlpatterns = [
    path("", views.computes, name="computes"),
    path(
        "add_tcp_host/",
        views.compute_create,
        {"FormClass": forms.TcpComputeForm},
        name="add_tcp_host",
    ),
    path(
        "add_ssh_host/",
        views.compute_create,
        {"FormClass": forms.SshComputeForm},
        name="add_ssh_host",
    ),
    path(
        "add_tls_host/",
        views.compute_create,
        {"FormClass": forms.TlsComputeForm},
        name="add_tls_host",
    ),
    path(
        "add_socket_host/",
        views.compute_create,
        {"FormClass": forms.SocketComputeForm},
        name="add_socket_host",
    ),
    path(
        "<int:compute_id>/",
        include(
            [
                path("", views.overview, name="overview"),
                path("update/", views.compute_update, name="compute_update"),
                path("delete/", views.compute_delete, name="compute_delete"),
                path("statistics", views.compute_graph, name="compute_graph"),
                path("instances/", views.instances, name="instances"),
                path("storages/", storages, name="storages"),
                path("storage/<str:pool>/volumes/", get_volumes, name="volumes"),
                path("storage/<str:pool>/", storage, name="storage"),
                path(
                    "storage/<str:pool>/create_volume/",
                    create_volume,
                    name="create_volume",
                ),
                path("networks/", networks, name="networks"),
                path("network/<str:pool>/", network, name="network"),
                path("interfaces/", interfaces, name="interfaces"),
                path("interface/<str:iface>/", interface, name="interface"),
                path("nwfilters/", nwfilters, name="nwfilters"),
                path("nwfilter/<str:nwfltr>/", nwfilter, name="nwfilter"),
                path("virtsecrets/", secrets, name="virtsecrets"),
                path(
                    "archs/<str:arch>/machines/",
                    views.get_compute_machine_types,
                    name="machines",
                ),
                path(
                    "archs/<str:arch>/machines/<str:machine>/disks/<str:disk>/buses/",
                    views.get_compute_disk_buses,
                    name="buses",
                ),
                path(
                    "archs/<str:arch>/machines/<str:machine>/capabilities/",
                    views.get_dom_capabilities,
                    name="domcaps",
                ),
            ]
        ),
    ),
]
