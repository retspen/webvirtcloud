from django.urls import path, re_path
from . import views

urlpatterns = [
    path('', views.showlogs, name='showlogs'),
    path('<int:page>/', views.showlogs, name='showlogspage'),
    path('vm_logs/<vname>/', views.vm_logs, name='vm_logs'),
]
