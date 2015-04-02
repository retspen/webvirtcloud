from django.conf.urls import url
from . import views

urlpatterns =[
    url(r'^$', views.computes, name='computes'),
    url(r'^overview/(\d+)/$', views.overview, name='overview'),
    url(r'^statistics/(\d+)/$', views.compute_graph, name='compute_graph'),
]
