from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^$', views.allinstances, name='allinstances'),
    url(r'^(?P<compute_id>[0-9]+)/(?P<vname>[\w\-\.]+)/$',  views.instance, name='instance'),
    url(r'^statistics/(?P<compute_id>[0-9]+)/(?P<vname>[\w\-\.]+)/$', views.inst_graph, name='inst_graph'),
    url(r'^status/(?P<compute_id>[0-9]+)/(?P<vname>[\w\-\.]+)/$', views.inst_status, name='inst_status'),
    url(r'^guess_mac_address/(?P<vname>[\w\-\.]+)/$', views.guess_mac_address, name='guess_mac_address'),
    url(r'^guess_clone_name/$', views.guess_clone_name, name='guess_clone_name'),
    url(r'^random_mac_address/$', views.random_mac_address, name='random_mac_address'),
    url(r'^check_instance/(?P<vname>[\w\-\.]+)/$', views.check_instance, name='check_instance'),
    url(r'^sshkeys/(?P<vname>[\w\-\.]+)/$', views.sshkeys, name='sshkeys'),
]
