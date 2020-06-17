from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='logout.html'), name='logout'),
    path('profile/', views.profile, name='profile'),
    path('profile/<int:user_id>/', views.account, name='account'),
    path('change_password/', views.change_password, name='change_password'),
    path('user_instance/create/<int:user_id>/', views.user_instance_create, name='user_instance_create'),
    path('user_instance/<int:pk>/update/', views.user_instance_update, name='user_instance_update'),
    path('user_instance/<int:pk>/delete/', views.user_instance_delete, name='user_instance_delete'),
]
