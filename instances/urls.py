from django.urls import path

from . import views

app_name = 'instances'

urlpatterns = [
    path('', views.allinstances, name='index'),
    path('<int:compute_id>/<vname>/', views.instance, name='instance'),
    path('statistics/<int:compute_id>/<vname>/', views.inst_graph, name='inst_graph'),
    path('status/<int:compute_id>/<vname>/', views.inst_status, name='inst_status'),
    path('guess_mac_address/<vname>/', views.guess_mac_address, name='guess_mac_address'),
    path('guess_clone_name/', views.guess_clone_name, name='guess_clone_name'),
    path('random_mac_address/', views.random_mac_address, name='random_mac_address'),
    path('check_instance/<vname>/', views.check_instance, name='check_instance'),
    path('sshkeys/<vname>/', views.sshkeys, name='sshkeys'),
]
