from django.urls import path, re_path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='logout.html'), name='logout'),
    path('profile/', views.profile, name='profile'), path('', views.accounts, name='accounts'),
    re_path(r'^profile/(?P<user_id>[0-9]+)/$', views.account, name='account'),
]
