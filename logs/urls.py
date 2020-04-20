from django.urls import path, re_path
from . import views

urlpatterns = [
    path('', views.showlogs, name='showlogs'),
    re_path(r'^(?P<page>[0-9]+)/$', views.showlogs, name='showlogspage'),
    re_path(r'^vm_logs/(?P<vname>[\w\-\.]+)/$', views.vm_logs, name='vm_logs'),
]
