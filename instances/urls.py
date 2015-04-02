from django.conf.urls import url
from . import views

urlpatterns =[
    url(r'^(?P<compute_id>[0-9]+)/(?P<vname>[\w\-\.]+)/$', views.instance, name='instance'),
    url(r'^statistics/(?P<compute_id>[0-9]+)/(?P<vname>[\w\-\.]+)/$', views.inst_graph, name='inst_graph'),
    url(r'^status/(?P<compute_id>[0-9]+)/(?P<vname>[\w\-\.]+)/$', views.inst_status, name='inst_status'),
]
