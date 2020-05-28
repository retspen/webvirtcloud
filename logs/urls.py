from django.urls import path, re_path
from . import views

urlpatterns = [
    re_path(r'^vm_logs/(?P<vname>[\w\-\.]+)/$', views.vm_logs, name='vm_logs'),
]
