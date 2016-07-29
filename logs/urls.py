from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^$', views.showlogs, name='showlogs'),
    url(r'^(?P<page>[0-9]+)/$', views.showlogs, name='showlogspage'),
]
