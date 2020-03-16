from django.urls import path, re_path
from . import views

urlpatterns = [
    path('', views.allinstances, name='allinstances'),
    re_path(r'^(?P<compute_id>[0-9]+)/(?P<vname>[\w\-\.]+)/$',  views.instance, name='instance'),
    re_path(r'^statistics/(?P<compute_id>[0-9]+)/(?P<vname>[\w\-\.]+)/$', views.inst_graph, name='inst_graph'),
    re_path(r'^status/(?P<compute_id>[0-9]+)/(?P<vname>[\w\-\.]+)/$', views.inst_status, name='inst_status'),
    re_path(r'^guess_mac_address/(?P<vname>[\w\-\.]+)/$', views.guess_mac_address, name='guess_mac_address'),
    re_path(r'^guess_clone_name/$', views.guess_clone_name, name='guess_clone_name'),
    re_path(r'^random_mac_address/$', views.random_mac_address, name='random_mac_address'),
    re_path(r'^check_instance/(?P<vname>[\w\-\.]+)/$', views.check_instance, name='check_instance'),
    re_path(r'^sshkeys/(?P<vname>[\w\-\.]+)/$', views.sshkeys, name='sshkeys'),
]
