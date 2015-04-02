from django.conf.urls import url
from . import views

urlpatterns =[
    url(r'^$', views.computes, name='computes'),
    url(r'^overview/(?P<compute_id>[0-9]+)/$', views.overview, name='overview'),
    url(r'^statistics/(?P<compute_id>[0-9]+)/$', views.compute_graph, name='compute_graph'),
]
