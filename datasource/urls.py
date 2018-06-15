from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^openstack/$',
        views.os_index, name='ds_openstack_index'),
    url(r'^openstack/(?P<version>[\w\-\.]+)/meta_data.json$',
        views.os_metadata_json, name='ds_openstack_metadata'),
    url(r'^openstack/(?P<version>[\w\-\.]+)/user_data$',
        views.os_userdata, name='ds_openstack_userdata'),
]
