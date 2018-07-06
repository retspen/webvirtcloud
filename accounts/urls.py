from django.conf.urls import url
from django.contrib import auth
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    url(r'^login/$', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    url(r'^logout/$', auth_views.LogoutView.as_view(template_name='logout.html'), name='logout'),
    url(r'^profile/$', views.profile, name='profile'), url(r'^$', views.accounts, name='accounts'),
    url(r'^profile/(?P<user_id>[0-9]+)/$', views.account, name='account'),
]
