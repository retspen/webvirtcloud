from django.conf.urls import url
from . import views

urlpatterns =[
    url(r'^(\d+)/([\w\-\.]+)/$', views.instance, name='instance'),
    url(r'^statistics/(\d+)/([\w\-\.]+)/$', views.inst_graph, name='inst_graph'),
    url(r'^status/(\d+)/([\w\-\.]+)/$', views.inst_status, name='inst_status'),
]
