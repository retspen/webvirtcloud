from django.conf.urls import url
from . import views

urlpatterns =[
    url(r'^login/$', 'django.contrib.auth.views.login', {'template_name': 'login.html'}, name='login'),
    url(r'^logout/$', 'django.contrib.auth.views.logout', {'template_name': 'logout.html'}, name='logout'),
    url(r'^profile/$', views.profile, name='profile'),
    url(r'^$', views.accounts, name='accounts'),
    url(r'^profile/(\d+)/$', views.account, name='account'),
]
