from django.urls import path

from . import views

urlpatterns = [
    path("openstack/", views.os_index, name="ds_openstack_index"),
    path(
        "openstack/<version>/meta_data.json",
        views.os_metadata_json,
        name="ds_openstack_metadata",
    ),
    path(
        "openstack/<version>/user_data", views.os_userdata, name="ds_openstack_userdata"
    ),
    path("vdi/<int:compute_id>/<vname>/", views.get_vdi_url, name="vdi_url"),
]
